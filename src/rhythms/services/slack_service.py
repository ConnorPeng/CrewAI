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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SlackBot:
    def __init__(self, github_service: GitHubService):
        """Initialize the Slack Bot with Slack credentials."""
        self.app_token = os.getenv("SLACK_APP_TOKEN")
        self.bot_token = os.getenv("SLACK_BOT_TOKEN")
        self.github_service = github_service
        
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
        self.socket_client = SocketModeClient(
            app_token=self.app_token,
            web_client=self.client
        )
        
        self.event_counter = 0
        self.user_responses = {} 
        
        # Set up message handler
        self._setup_handler()
        logger.info("SlackBot initialized successfully")
        
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
                    key = (channel_id, user_id)
                    logger.info(f"connor debugging 2: Checking if {key} is in user_responses")
                    if key in self.user_responses:
                        logger.info(f"Found waiting response queue for {key}")
                        try:
                            self.user_responses[key].put(text)
                            logger.info(f"Successfully put response in queue for {key}")
                        except Exception as e:
                            logger.error(f"Error putting response in queue: {str(e)}")

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
        text = event.get("text", "").strip()
        thread_ts = None
        
        if "standup" in text.lower():
            try:
                # Start a new thread for this standup
                response = self.client.chat_postMessage(
                    channel=channel_id,
                    text=f"Starting standup process for <@{user_id}>... 🚀\nI'll gather your GitHub activity and help create your standup update."
                )
                thread_ts = response['ts']

                def output_callback(message):
                    """Callback for CrewAI output"""
                    logger.info(f"Received message from CrewAI: {message} type: {type(message)}")
                    if not message:
                        return
                        
                    # Format the message for Slack
                    if isinstance(message, dict):
                        formatted_message = self._format_dict_for_slack(message)
                    else:
                        formatted_message = str(message)
                        
                    logger.info(f"Sending formatted message to Slack: {formatted_message}")
                    self._send_to_slack(channel_id, formatted_message, thread_ts)

                # Initialize Rhythms with callbacks
                rhythms = Rhythms(
                    slack_interaction_callback=lambda prompt: self._get_user_input(
                        channel_id, user_id, prompt, thread_ts
                    ),
                    slack_output_callback=output_callback
                )
                
                standup_crew = rhythms.standup_crew()
                result = standup_crew.kickoff()

                # Send the final standup result
                if result:
                    formatted_result = self._format_dict_for_slack(result) if isinstance(result, dict) else str(result)
                    self._send_to_slack(
                        channel_id,
                        f"Here's your standup summary:\n{formatted_result}",
                        thread_ts
                    )

            except Exception as e:
                logger.error(f"Error running standup: {str(e)}")
                self._send_to_slack(
                    channel_id,
                    "Sorry, I encountered an error while running the standup. Please try again.",
                    thread_ts
                )

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
        logger.info(f"connor debugging 1: Getting user input for {user_id} in channel {channel_id}")
        # Create a new response queue for this request
        response_queue = Queue()
        key = (channel_id, user_id)
        
        # Clear any existing queue for this user
        if key in self.user_responses:
            old_queue = self.user_responses[key]
            try:
                # Clear the old queue
                while not old_queue.empty():
                    old_queue.get_nowait()
            except:
                pass
        
        self.user_responses[key] = response_queue
        logger.info(f"Created new response queue for {key}")

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
        logger.info(f"Sent prompt to user {user_id} in channel {channel_id}")

        # Wait for response with timeout
        try:
            logger.info(f"Waiting for response from {key}")
            response = response_queue.get(timeout=300)  # 5 minute timeout
            logger.info(f"Received response from {key}: {response}")
            
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
            
            # Send a more helpful error message based on the type of error
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
            # Always clean up
            if key in self.user_responses:
                del self.user_responses[key]
                logger.info(f"Cleaned up response queue for {key}")

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

    def start(self) -> None:
        """Start the Slack bot."""
        logger.info("Starting Slack bot...")
        self.socket_client.connect()
        
        # Keep the bot running
        from time import sleep
        while True:
            sleep(1) 