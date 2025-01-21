from slack_sdk.web import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest
from typing import Dict, Any, List
import os
import logging
import ssl
from ..services.github_service import GitHubService
from ..crew import Rhythms
from datetime import datetime
import time
import re
from queue import Queue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SlackBot:
    _instance = None
    
    def __new__(cls, github_service: GitHubService):
        if cls._instance is None:
            cls._instance = super(SlackBot, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, github_service: GitHubService):
        """Initialize the Slack Bot with Slack credentials."""
        if self._initialized:
            return
            
        self.app_token = os.getenv("SLACK_APP_TOKEN")
        self.bot_token = os.getenv("SLACK_BOT_TOKEN")
        self.github_service = github_service
        self.socket_client = None
        self.client = None
        self.event_counter = 0
        self.user_responses = {}
        # Initialize Rhythms with default callbacks
        self.rhythms = Rhythms()  # Initialize early
        self.current_thread_ts = None  # Track current thread
        self.active_standup = None  # Track active standup
        self._initialized = True
        
        if not self.app_token or not self.bot_token:
            raise ValueError("SLACK_APP_TOKEN and SLACK_BOT_TOKEN must be set")
            
        # Create SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
            
        # Initialize Slack clients with SSL context
        self.client = WebClient(
            token=self.bot_token,
            ssl=ssl_context
        )
        
        logger.info("SlackBot initialized successfully")

    def start(self) -> None:
        """Start the Slack bot."""
        try:
            logger.info("Starting Slack bot...")
            if self.socket_client:
                logger.info("Cleaning up existing socket client...")
                self.cleanup()
                
            self.socket_client = SocketModeClient(
                app_token=self.app_token,
                web_client=self.client
            )
            self._setup_handler()
            self.socket_client.connect()
            
            # For testing: Trigger notification immediately after connection
            # if hasattr(self, 'scheduler') and self.scheduler:
            #     logger.info("Testing: Triggering immediate notification...")
            #     self.scheduler.prepare_and_notify()
            
            # Keep the bot running and check schedules
            last_schedule_check = 0
            while True:
                current_time = time.time()
                # Check schedules every minute
                if current_time - last_schedule_check >= 60:
                    if hasattr(self, 'scheduler') and self.scheduler:
                        self.scheduler.check_schedules()
                    last_schedule_check = current_time
                time.sleep(1)
        except Exception as e:
            logger.error(f"Error in Slack bot: {e}")
            self.cleanup()
            raise

    def cleanup(self) -> None:
        """Clean up resources."""
        try:
            if hasattr(self, '_initialized') and self._initialized:
                # Clear any active standup
                self.active_standup = None
                self.current_thread_ts = None
                self.rhythms = None
                self.user_responses = {}
                
                # Close the socket client if it exists
                if hasattr(self, 'app') and self.app:
                    self.app.close()
                logger.info("SlackBot cleaned up successfully")
        except Exception as e:
            logger.error(f"Error cleaning up socket client: {e}")

    def __del__(self):
        """Destructor to ensure cleanup."""
        self.cleanup()

    def _setup_handler(self) -> None:
        """Setup the socket mode event handler."""
        def socket_handler(client: SocketModeClient, req: SocketModeRequest) -> None:
            logger.info(f"connor debugging Received request: {req.type}")
            if req.type == "events_api":
                event = req.payload.get("event", {})
                event_type = event.get("type")
                
                # Log all incoming events for debugging
                logger.info(f"Received event: {event_type}")
                logger.info(f"Event payload: {event}")
                
                # Always acknowledge the request first
                response = SocketModeResponse(envelope_id=req.envelope_id)
                client.send_socket_mode_response(response)
                
                # Handle app mentions (standup command)
                if event_type == "app_mention":
                    channel_id = event.get("channel")
                    user_id = event.get("user")
                    thread_ts = event.get("thread_ts", event.get("ts"))
                    text = event.get("text", "").strip().lower()
                    
                    # Set this as the active standup for new standups
                    if "standup" in text and not any(cmd in text for cmd in ["pause", "resume"]):
                        self.active_standup = thread_ts
                    
                    self.event_counter += 1
                    logger.info(f"Received Slack command #{self.event_counter}: {req.payload}")
                    self._handle_standup_command(event)
                
                # Handle message responses in threads
                elif event_type == "message":
                    channel_id = event.get("channel")
                    user_id = event.get("user")
                    thread_ts = event.get("thread_ts")
                    bot_id = event.get("bot_id")
                    subtype = event.get("subtype")
                    
                    logger.info(f"Processing message event:")
                    logger.info(f"- Channel: {channel_id}")
                    logger.info(f"- User: {user_id}")
                    logger.info(f"- Thread: {thread_ts}")
                    logger.info(f"- Bot ID: {bot_id}")
                    logger.info(f"- Subtype: {subtype}")
                    
                    # Ignore bot messages, messages not in threads, and message edits
                    if bot_id or not thread_ts or subtype:
                        logger.info("Ignoring message due to filters")
                        return
                        
                    text = event.get("text", "").strip()
                    logger.info(f"Received thread message from {user_id} in {channel_id}: {text}")
                    
                    # Check if this is a response we're waiting for
                    key = (channel_id, user_id, thread_ts)
                    logger.info(f"Checking for response queue with key: {key}")
                    logger.info(f"Current response queues: {list(self.user_responses.keys())}")
                    
                    if key in self.user_responses:
                        response_data = self.user_responses[key]
                        logger.info(f"Found waiting response queue for {key}")
                        try:
                            response_data['queue'].put(text)
                            logger.info(f"Successfully put response in queue for {key}")
                        except Exception as e:
                            logger.error(f"Error putting response in queue: {str(e)}")
                            logger.exception("Full traceback:")
                    else:
                        logger.info(f"No waiting queue found for key {key}")

        self.socket_client.socket_mode_request_listeners.append(socket_handler)
        logger.info("Socket handler setup complete")

    def _handle_standup_command(self, event: Dict[str, Any]) -> None:
        """Handle the standup command."""
        channel_id = event["channel"]
        slack_user_id = event["user"]  # This is the Slack user ID
        logger.info(f"Received standup command from {slack_user_id} in channel {channel_id}")
        text = event.get("text", "").strip().lower()
        thread_ts = event.get("thread_ts", event.get("ts"))
        
        # Get user from database
        try:
            # Try to get user by Slack ID
            user_data = self.rhythms.memory_service.get_user_by_slack_id(slack_user_id)
            if not user_data:
                # If user not found, return error message
                self._send_to_slack(
                    channel_id,
                    "User not found. Please register first before using the standup feature.",
                    thread_ts
                )
                return
            
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            self._send_to_slack(
                channel_id,
                "Error retrieving user profile. Please contact support.",
                thread_ts
            )
            return
        
        logger.info(f"connor debuggingUser self.active_standup: {self.active_standup}")
        # Handle pause command
        if "pause" in text:
            # Check if there's any active standup (regardless of thread)
            if not self.active_standup:
                self._send_to_slack(
                    channel_id,
                    "No active standup session to pause.",
                    thread_ts
                )
                return
            
            # Get the active standup thread for saving state
            active_thread = self.active_standup
                
            session_id = self.rhythms.save_conversation_state(slack_user_id)
            if session_id:
                # Send message to both the original thread and the thread where pause was requested
                self._send_to_slack(
                    channel_id,
                    "Standup session paused. Use `@bot resume` to continue later.",
                    active_thread
                )
                if thread_ts != active_thread:
                    self._send_to_slack(
                        channel_id,
                        "Standup session paused. Use `@bot resume` to continue later.",
                        thread_ts
                    )
                # Clear active standup on successful pause
                self.active_standup = None
                self.current_thread_ts = None
            else:
                self._send_to_slack(
                    channel_id,
                    "Failed to pause the standup session. Please try again.",
                    thread_ts
                )
            return
            
        # Handle resume command
        if "resume" in text:
            if not self.rhythms:
                self.rhythms = Rhythms(
                    slack_interaction_callback=lambda prompt: self._get_user_input(
                        channel_id, slack_user_id, prompt, self.current_thread_ts
                    )
                )
            
            # Get the most recent session
            conversations = self.rhythms.memory_service.list_user_conversations(slack_user_id)
            if not conversations:
                self._send_to_slack(
                    channel_id,
                    "No paused session found to resume.",
                    self.current_thread_ts
                )
                return
                
            most_recent_session = conversations[0]['session_id']
            if self.rhythms.resume_conversation(most_recent_session):
                # Start a new thread for the resumed session
                response = self.client.chat_postMessage(
                    channel=channel_id,
                    text=f"Continuing standup for <@{slack_user_id}>... 🔄"
                )
                self.current_thread_ts = response['ts']
                # Set this as the active standup
                self.active_standup = self.current_thread_ts
                
                standup_crew = self.rhythms.standup_crew()
                result = standup_crew.kickoff()
                logger.info(f"Raw standup result: {result}")  # Add debug logging
                
                if result:
                    formatted_result = (
                        self._format_dict_for_slack(result.to_dict())
                    )
                    logger.info(f"Formatted result: {formatted_result}")  # Add debug logging
                    
                    self._send_to_slack(
                        channel_id,
                        formatted_result,
                        self.current_thread_ts
                    )
            else:
                self._send_to_slack(
                    channel_id,
                    "Could not resume the previous session. Please start a new standup.",
                    self.current_thread_ts
                )
            return
        
        # Handle regular standup command
        if "standup" in text:
            try:
                # Start a new thread for this standup
                response = self.client.chat_postMessage(
                    channel=channel_id,
                    text=f"Starting standup process for <@{slack_user_id}>... 🚀",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"Starting standup process for <@{slack_user_id}>... 🚀\nI'll gather your GitHub activity and help create your standup update.\n\nYou can use these commands during the standup:\n• `@bot pause` - Pause the current session\n• `@bot resume` - Resume your paused session"
                            }
                        }
                    ],
                    link_names=True
                )
                self.current_thread_ts = response['ts']
                # Set this as the active standup
                self.active_standup = self.current_thread_ts

                # Initialize Rhythms with callbacks using the new method
                self.rhythms = Rhythms(
                    slack_interaction_callback=lambda prompt: self._get_user_input(
                        channel_id, slack_user_id, prompt, self.current_thread_ts
                    )
                )
                
                # Initialize conversation state immediately
                self.rhythms.current_conversation_state = {
                    'status': 'active',
                    'thread_ts': self.current_thread_ts,
                    'channel_id': channel_id,
                    'user_id': slack_user_id,
                    'start_time': datetime.now().isoformat()
                }
                
                standup_crew = self.rhythms.standup_crew()
                result = standup_crew.kickoff()
                logger.info(f"Raw standup result: {result}")
                logger.info(f"connor debugging here 103 message output {result}")
                logger.info(f"connor debugging here 104 message output type {type(result)}")
                if result:
                    formatted_result = (
                        self._format_dict_for_slack(result.raw)
                    )
                    logger.info(f"Formatted result: {formatted_result}")  # Add debug logging
                    
                    self._send_to_slack(
                        channel_id,
                        formatted_result,
                        self.current_thread_ts
                    )
                    # Clear active standup when complete
                    self.active_standup = None

            except Exception as e:
                logger.error(f"Error running standup: {str(e)}")
                self._send_to_slack(
                    channel_id,
                    "Sorry, I encountered an error while running the standup. Please try again.",
                    self.current_thread_ts
                )
                # Clear active standup on error
                self.active_standup = None

    def _format_dict_for_slack(self, data: str) -> str:
        """Format a dictionary into a readable Slack message using Block Kit patterns."""
        logger.info(f"Input data to format: {data}")
        logger.info(f"Input data type: {type(data)}")
        
        # Check if this is markdown formatted text instead of a proper dict structure
        if isinstance(data, str):
            logger.info("Received markdown text in dict format")
            # Use the common formatting function
            sections = self._format_markdown_to_blocks(data, final=True)
            return {"blocks": sections}
        else:
            logger.info("Received non-string data in dict format")
            return {"blocks": []}

    def _format_markdown_to_blocks(self, markdown_text: str, user_id: str = None, include_prompt: bool = False, final: bool = False) -> List[Dict]:
        """Convert markdown text to Slack Block Kit format.
        
        Args:
            markdown_text: The markdown text to convert
            user_id: Optional user ID to mention in the review prompt
            include_prompt: Whether to include the review prompt section
            final: Whether this is a final standup report
        
        Returns:
            List of Block Kit blocks
        """
        sections = []
        current_section = None
        current_items = []
        
        for line in markdown_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            if line.startswith('# '):
                # Main header
                sections.append({
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🎯 Final Standup Report" if final else "📝 Standup Report Draft",
                        "emoji": True
                    }
                })
                sections.append({"type": "divider"})
            elif line.startswith('## '):
                # If we have a previous section, save it
                if current_section and current_items:
                    sections.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{current_section['emoji']} *{current_section['title']}*"
                        }
                    })
                    sections.append({
                        "type": "context",
                        "elements": [{
                            "type": "mrkdwn",
                            "text": "\n".join(current_items)
                        }]
                    })
                    sections.append({"type": "divider"})
                
                # Start new section
                section_title = line[2:].strip().rstrip(':')
                current_section = {
                    "title": section_title,
                    "emoji": "✅" if "Accomplishments" in section_title else 
                            "⚠️" if "Blockers" in section_title else 
                            "📋" if "Plans" in section_title else "📝"
                }
                current_items = []
            elif line.startswith('- '):
                # Format list items, handling links specially
                item = line[2:]
                # Convert markdown links to Slack format
                item = re.sub(r'\[(.*?)\]\((.*?)\)', r'<\2|\1>', item)
                current_items.append(f"• {item}")

        # Add the last section if exists
        if current_section and current_items:
            sections.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{current_section['emoji']} *{current_section['title']}*"
                }
            })
            sections.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": "\n".join(current_items)
                }]
            })
            sections.append({"type": "divider"})

        # Add review prompt section if requested and not final
        if include_prompt and user_id and not final:
            sections.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Hey <@{user_id}>, please review this standup draft and let me know if you'd like to make any changes. You can:\n• Add new items\n• Remove items\n• Edit existing items"
                }
            })

        return sections

    def _get_user_input(self, channel_id: str, user_id: str, prompt: str, thread_ts: str) -> str:
        """Get user input from Slack with a timeout."""
        logger.info(f"Getting user input for {user_id} in channel {channel_id} prompt: {prompt}")
        logger.info(f"Using thread_ts: {thread_ts}")
        
        # Create a new response queue for this request
        response_queue = Queue()
        key = (channel_id, user_id, thread_ts)
        
        # Store the queue and prompt
        self.user_responses[key] = {
            'queue': response_queue,
            'last_prompt': prompt,
            'timestamp': datetime.now().isoformat()
        }

        # Format the prompt into blocks
        sections = self._format_markdown_to_blocks(prompt, user_id, include_prompt=True)

        # Send message to Slack
        message = self.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Please review your standup draft",  # Fallback text
            blocks=sections,
            link_names=True
        )
        logger.info(f"Sent prompt message with ts: {message.get('ts')}")

        # Wait for response with timeout
        try:
            response = response_queue.get(timeout=300)  # 5 minute timeout
            logger.info(f"Got response: {response}")
            
            # Acknowledge receipt of response
            self.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="✅ Got your response! Processing and updating your standup summary..."
            )
            
            return response
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error getting response: {error_msg}")
            
            if "timeout" in error_msg.lower():
                error_response = "⚠️ No response received within the time limit. Please try the standup command again."
            else:
                error_response = "❌ There was an error processing your response. Please try the standup command again."
                
            self.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=error_response
            )
            return "No response received"
        finally:
            # Clean up the response queue
            if key in self.user_responses:
                del self.user_responses[key]

    def _send_to_slack(self, channel_id: str, message: str, thread_ts: str) -> None:
        """Send a message to Slack channel in thread using Block Kit for better formatting."""
        try:
            if not message:
                return
            
            logger.info(f"Sending message to Slack: {message}")
            
            # If message is already formatted with blocks
            if isinstance(message, dict) and "blocks" in message:
                self.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    blocks=message["blocks"],
                    text="Standup Update",  # Fallback text
                    unfurl_links=False,
                    unfurl_media=False,
                    parse='mrkdwn'
                )
                return
            
            # For string messages
            clean_message = str(message)
            if len(clean_message) > 3000:
                # Split long messages
                messages = [clean_message[i:i+3000] for i in range(0, len(clean_message), 3000)]
                for msg in messages:
                    blocks = self._create_message_blocks(msg)
                    self.client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=msg,  # Fallback text
                        blocks=blocks,
                        unfurl_links=False,
                        unfurl_media=False,
                        parse='mrkdwn'
                    )
            else:
                blocks = self._create_message_blocks(clean_message)
                self.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=clean_message,  # Fallback text
                    blocks=blocks,
                    unfurl_links=False,
                    unfurl_media=False,
                    parse='mrkdwn'
                )
            
        except Exception as e:
            logger.error(f"Error sending message to Slack: {str(e)}")
            logger.exception("Full traceback:")

    def _create_message_blocks(self, message: str) -> List[Dict]:
        """Create Block Kit blocks for message formatting."""
        blocks = []
        
        # If this is a standup update
        if "🎯" in message and "Standup Update" in message:
            # Add header
            blocks.append({
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Today's Standup Update 🎯",
                    "emoji": True
                }
            })
            
            # Add divider
            blocks.append({
                "type": "divider"
            })
            
            # Split into sections and process each
            sections = message.split("\n\n")
            for section in sections[1:]:  # Skip the header
                if not section.strip():
                    continue
                    
                # Parse section title and content
                lines = section.split("\n")
                if not lines:
                    continue
                    
                title_line = lines[0].strip()
                content_lines = lines[1:] if len(lines) > 1 else []
                
                # Extract emoji and title
                if " *" in title_line:
                    emoji, title = title_line.split(" *", 1)
                    title = title.replace("*", "")
                else:
                    emoji = "📝"
                    title = title_line
                    
                # Add section title
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{emoji} *{title}*"
                    }
                })
                
                # Add content as a context block with better formatting
                if content_lines:
                    content_text = "\n".join(content_lines)
                    blocks.append({
                        "type": "context",
                        "elements": [{
                            "type": "mrkdwn",
                            "text": content_text
                        }]
                    })
                
                # Add divider between sections
                blocks.append({
                    "type": "divider"
                })
                
        # For user prompts
        elif "Please respond in this thread" in message:
            blocks.extend([
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message.split("\n")[0]  # Main prompt
                    }
                },
                {
                    "type": "context",
                    "elements": [{
                        "type": "mrkdwn",
                        "text": ":bulb: _Type your response below. Your input will be used to update the standup summary._"
                    }]
                }
            ])
            
        # For acknowledgment messages
        elif "Got your response!" in message:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": ":white_check_mark: _Got your response! Processing and updating your standup summary..._"
                }]
            })
            
        # For error messages
        elif "Error" in message or "error" in message:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: {message}"
                }
            })
            
        # For all other messages
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message
                }
            })
        
        # Remove consecutive dividers and trailing divider
        cleaned_blocks = []
        for i, block in enumerate(blocks):
            if block["type"] == "divider":
                if i == len(blocks) - 1:  # Skip trailing divider
                    continue
                if i > 0 and blocks[i-1]["type"] == "divider":  # Skip consecutive dividers
                    continue
            cleaned_blocks.append(block)
        
        return cleaned_blocks

    def cleanup(self) -> None:
        """Clean up resources."""
        if self.socket_client:
            try:
                self.socket_client.close()
                self.socket_client = None
            except Exception as e:
                logger.error(f"Error cleaning up socket client: {e}") 

    async def handle_mention(self, event: Dict):
        """Handle app mention events."""
        try:
            channel_id = event['channel']
            user_id = event['user']
            thread_ts = event.get('thread_ts', event['ts'])

            # Check if there's already an active standup
            if self.active_standup:
                # If the active standup is in a different thread, notify the user
                if self.active_standup != thread_ts:
                    await self.client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text="There's already an active standup in another thread. Please wait for it to complete or use that thread."
                    )
                return
            
            # Set this as the active standup
            self.active_standup = thread_ts

            # Initialize conversation state
            self.current_conversation_state = {
                "status": "active",
                "thread_ts": thread_ts,
                "channel_id": channel_id,
                "user_id": user_id,
                "start_time": datetime.now().isoformat()
            }

            # Start the standup process
            await self._start_standup(channel_id, user_id, thread_ts)

        except Exception as e:
            logger.error(f"Error handling mention: {e}")
            if thread_ts:
                await self.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=f"Error starting standup: {str(e)}"
                )

    def _handle_output(self, agent_name: str, content: str) -> None:
        """Handle output from an agent."""
        if "FINAL STANDUP:" in content:
            # Clear the active standup when finished
            self.active_standup = None
            
        # ... rest of the existing _handle_output code ... 

    def _handle_error(self, error: Exception, channel_id: str = None, thread_ts: str = None):
        """Handle errors by cleaning up state and notifying the user."""
        logger.error(f"Error in SlackBot: {error}")
        # Clear active standup on error
        self.active_standup = None
        if channel_id and thread_ts:
            try:
                self.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=f"An error occurred: {str(error)}"
                )
            except Exception as e:
                logger.error(f"Error sending error message: {e}") 

    def set_scheduler(self, scheduler):
        """Set the scheduler service reference."""
        self.scheduler = scheduler 