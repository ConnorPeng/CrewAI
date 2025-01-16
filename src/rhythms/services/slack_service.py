from slack_sdk.web import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest
from typing import Dict, Any
import os
import logging
import ssl
from ..services.github_service import GitHubService
from ..crew import Rhythms
from datetime import datetime

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
        self.rhythms = None  # Will be set when handling commands
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
            
            # Keep the bot running
            from time import sleep
            while True:
                sleep(1)
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
            if req.type == "events_api":
                event = req.payload.get("event", {})
                event_type = event.get("type")
                
                # Always acknowledge the request first
                response = SocketModeResponse(envelope_id=req.envelope_id)
                client.send_socket_mode_response(response)
                
                # Handle app mentions (standup command)
                if event_type == "app_mention":
                    channel_id = event.get("channel")
                    user_id = event.get("user")
                    thread_ts = event.get("thread_ts", event.get("ts"))
                    text = event.get("text", "").strip().lower()
                    
                    # Check if this is a duplicate event
                    event_key = f"{channel_id}:{user_id}:{thread_ts}:{text}"
                    current_time = datetime.now()
                    
                    # Store recent events with timestamp to prevent duplicates
                    if not hasattr(self, '_recent_events'):
                        self._recent_events = {}
                    
                    # Check if we've seen this exact event in the last 2 seconds
                    if event_key in self._recent_events:
                        last_time = self._recent_events[event_key]
                        if (current_time - last_time).total_seconds() < 2:
                            logger.info(f"Skipping duplicate event: {event_key}")
                            return
                    
                    # Update the event timestamp
                    self._recent_events[event_key] = current_time
                    
                    # Clean up old events (older than 5 seconds)
                    self._recent_events = {k: v for k, v in self._recent_events.items() 
                                         if (current_time - v).total_seconds() < 5}
                    
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
                    
                    # Ignore bot messages and messages not in threads
                    if bot_id or not thread_ts:
                        return
                        
                    text = event.get("text", "").strip()
                    logger.info(f"Received thread message from {user_id} in {channel_id}: {text}")
                    
                    # Check if this is a response we're waiting for
                    key = (channel_id, user_id, thread_ts)
                    logger.info(f"Checking for response queue with key: {key}")
                    
                    if key in self.user_responses:
                        response_data = self.user_responses[key]
                        logger.info(f"Found waiting response queue for {key}")
                        try:
                            response_data['queue'].put(text)
                            logger.info(f"Successfully put response in queue for {key}")
                        except Exception as e:
                            logger.error(f"Error putting response in queue: {str(e)}")
                    else:
                        logger.info(f"No waiting queue found for key {key}. Available keys: {list(self.user_responses.keys())}")

        self.socket_client.socket_mode_request_listeners.append(socket_handler)
        logger.info("Socket handler setup complete")

    def _handle_message(self, event: Dict[str, Any]) -> None:
        """Handle incoming messages."""
        channel_id = event["channel"]
        user_id = event["user"]
        bot_id = event.get("bot_id")
        text = event.get("text", "").strip()
        logger.info(f"Received message from {user_id}: {text}")
        
        if bot_id:
            logger.info(f"Ignoring message from bot: {event}")
            return

        # Process crew-related commands
        if "crew" in text.lower():
            self._handle_crew_command(channel_id, text)

    def _handle_crew_command(self, channel_id: str, text: str) -> None:
        """Handle crew-related commands."""
        try:
            # Example: Get crew information
            crew_info = self.github_service.get_crew_info()
            
            # Format the response
            response = "Current Crew Information:\n"
            for member in crew_info:
                response += f"• {member['name']} - {member['role']}\n"
            
            self.client.chat_postMessage(
                channel=channel_id,
                text=response
            )
                
        except Exception as e:
            logger.error(f"Error handling crew command: {str(e)}")
            self.client.chat_postMessage(
                channel=channel_id,
                text="Sorry, I encountered an error. Please try again."
            )

    def _handle_standup_command(self, event: Dict[str, Any]) -> None:
        """Handle the standup command."""
        channel_id = event["channel"]
        user_id = event["user"]
        text = event.get("text", "").strip().lower()
        thread_ts = event.get("thread_ts", event.get("ts"))
        
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
            
            # If we don't have a state yet but we have an active standup, create one
            if not (self.rhythms and self.rhythms.current_conversation_state):
                if not self.rhythms:
                    self.rhythms = Rhythms(
                        slack_interaction_callback=lambda prompt: self._get_user_input(
                            channel_id, user_id, prompt, active_thread
                        ),
                        slack_output_callback=lambda msg: self._send_to_slack(
                            channel_id,
                            self._format_dict_for_slack(msg) if isinstance(msg, dict) else str(msg),
                            active_thread
                        )
                    )
                self.rhythms.current_conversation_state = {
                    'status': 'active',
                    'thread_ts': active_thread,
                    'channel_id': channel_id,
                    'user_id': user_id
                }
                
            session_id = self.rhythms.save_conversation_state()
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
                        channel_id, user_id, prompt, self.current_thread_ts
                    ),
                    slack_output_callback=lambda msg: self._send_to_slack(
                        channel_id, 
                        self._format_dict_for_slack(msg) if isinstance(msg, dict) else str(msg), 
                        self.current_thread_ts
                    )
                )
            
            # Get the most recent session
            conversations = self.rhythms.memory_service.list_user_conversations("ConnorPeng")
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
                    text=f"Continuing standup for <@{user_id}>... 🔄"
                )
                self.current_thread_ts = response['ts']
                # Set this as the active standup
                self.active_standup = self.current_thread_ts
                
                standup_crew = self.rhythms.standup_crew()
                result = standup_crew.kickoff()
                
                if result:
                    formatted_result = (
                        self._format_dict_for_slack(result)
                        if isinstance(result, dict)
                        else str(result)
                    )
                    self._send_to_slack(
                        channel_id,
                        f"Resumed standup completed:\n{formatted_result}",
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
                    text=f"Starting standup process for <@{user_id}>... 🚀\nI'll gather your GitHub activity and help create your standup update.\n\nYou can use these commands during the standup:\n• `@bot pause` - Pause the current session\n• `@bot resume` - Resume your paused session"
                )
                self.current_thread_ts = response['ts']
                # Set this as the active standup
                self.active_standup = self.current_thread_ts

                def output_callback(message):
                    """Callback for CrewAI output"""
                    if not message:
                        return
                    formatted_message = (
                        self._format_dict_for_slack(message)
                        if isinstance(message, dict)
                        else str(message)
                    )
                    self._send_to_slack(channel_id, formatted_message, self.current_thread_ts)

                # Initialize Rhythms with callbacks
                self.rhythms = Rhythms(
                    slack_interaction_callback=lambda prompt: self._get_user_input(
                        channel_id, user_id, prompt, self.current_thread_ts
                    ),
                    slack_output_callback=output_callback
                )
                
                # Initialize conversation state immediately
                self.rhythms.current_conversation_state = {
                    'status': 'active',
                    'thread_ts': self.current_thread_ts,
                    'channel_id': channel_id,
                    'user_id': user_id,
                    'start_time': datetime.now().isoformat()
                }
                
                standup_crew = self.rhythms.standup_crew()
                result = standup_crew.kickoff()

                if result:
                    formatted_result = (
                        self._format_dict_for_slack(result)
                        if isinstance(result, dict)
                        else str(result)
                    )
                    self._send_to_slack(
                        channel_id,
                        f"Here's your standup summary:\n{formatted_result}",
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

    def _format_dict_for_slack(self, data: Dict) -> str:
        """Format a dictionary into a readable Slack message."""
        if not isinstance(data, dict):
            return str(data)
            
        formatted_sections = []
        
        # Handle GitHub activity data
        if "completed_work" in data:
            if data["completed_work"]:
                formatted_sections.append("*:white_check_mark: Completed Work:*")
                for item in data["completed_work"]:
                    formatted_sections.append(f"• {item}")
            
        if "work_in_progress" in data:
            if data["work_in_progress"]:
                formatted_sections.append("\n*:construction: Work in Progress:*")
                for item in data["work_in_progress"]:
                    formatted_sections.append(f"• {item}")
            
        if "potential_blockers" in data:
            if data["potential_blockers"]:
                formatted_sections.append("\n*:warning: Potential Blockers:*")
                for item in data["potential_blockers"]:
                    formatted_sections.append(f"• {item}")
                    
        # If no data in standard categories, format generically
        if not formatted_sections:
            for key, value in data.items():
                formatted_key = key.replace("_", " ").title()
                if isinstance(value, list):
                    formatted_sections.append(f"*{formatted_key}:*")
                    for item in value:
                        formatted_sections.append(f"• {item}")
                else:
                    formatted_sections.append(f"*{formatted_key}:* {value}")
                    
        return "\n".join(formatted_sections) if formatted_sections else "No data to display"

    def _get_user_input(self, channel_id: str, user_id: str, prompt: str, thread_ts: str) -> str:
        """Get user input from Slack with a timeout."""
        import threading
        from queue import Queue
        logger.info(f"Getting user input for {user_id} in channel {channel_id} prompt: {prompt}")
        
        # Create a new response queue for this request
        response_queue = Queue()
        key = (channel_id, user_id, thread_ts)  # Add thread_ts to make the key unique per thread
        
        # Store the queue and prompt
        self.user_responses[key] = {
            'queue': response_queue,
            'last_prompt': prompt,
            'timestamp': datetime.now().isoformat()
        }

        # Format the prompt for better readability
        formatted_prompt = (
            f"<@{user_id}> {prompt}\n"
            "Please respond in this thread. Your response will be used to update your standup summary."
        )

        # Send the prompt to the user
        self.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=formatted_prompt,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": formatted_prompt
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "💡 _Type your response below. Be as detailed as you'd like._"
                        }
                    ]
                }
            ]
        )

        # Wait for response with timeout
        try:
            response = response_queue.get(timeout=300)  # 5 minute timeout
            logger.info(f"Got response: {response}")
            
            # Update conversation state
            if self.rhythms and not self.rhythms.current_conversation_state:
                self.rhythms.current_conversation_state = {
                    'status': 'active',
                    'last_prompt': prompt,
                    'thread_ts': thread_ts,
                    'channel_id': channel_id,
                    'user_id': user_id
                }
            
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
            if key in self.user_responses:
                del self.user_responses[key]

    def _send_to_slack(self, channel_id: str, message: str, thread_ts: str) -> None:
        """Send a message to Slack channel in thread."""
        try:
            # Clean up the message
            message = str(message).strip()
            if not message:
                return
            
            # Split long messages
            max_length = 3000
            messages = [message[i:i + max_length] for i in range(0, len(message), max_length)]
            
            for msg in messages:
                # Format code blocks properly
                if '```' in msg:
                    msg = f"```\n{msg.replace('```', '')}\n```"
                
                self.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=msg,
                    unfurl_links=False,
                    unfurl_media=False
                )
            
        except Exception as e:
            logger.error(f"Error sending message to Slack: {str(e)}")

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