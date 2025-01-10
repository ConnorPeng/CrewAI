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
        
        # Set up message handler
        self._setup_handler()
        logger.info("SlackBot initialized successfully")
        
    def _setup_handler(self) -> None:
        """Setup the socket mode event handler."""
        def socket_handler(client: SocketModeClient, req: SocketModeRequest) -> None:
            event = req.payload.get("event", {})
            event_type = event.get("type")
            if req.type == "events_api" and event_type == "app_mention":
                self.event_counter += 1
                logger.info(f"Received Slack command #{self.event_counter}: {req.payload}")

                # Acknowledge the command immediately
                response = SocketModeResponse(envelope_id=req.envelope_id)
                client.send_socket_mode_response(response)

                self._handle_standup_command(event)
        

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
        """Handle the /standup command."""
        channel_id = event["channel"]
        user_id = event["user"]
        bot_id = event.get("bot_id")
        text = event.get("text", "").strip()
        logger.info(f"Received message from {user_id}: {text}")
        if "standup" in text.lower():
            try:
                # Send initial response
                self.client.chat_postMessage(
                    channel=channel_id,
                    text=f"Starting standup process for <@{user_id}>... 🚀"
                )

                # Initialize and run the Rhythms crew
                rhythms = Rhythms()
                standup_crew = rhythms.standup_crew()
                result = standup_crew.kickoff()

                # Send the standup result back to Slack
                self.client.chat_postMessage(
                    channel=channel_id,
                    text=f"Standup Summary:\n```\n{result}\n```"
                )

            except Exception as e:
                logger.error(f"Error running standup: {str(e)}")
                self.client.chat_postMessage(
                    channel=channel_id,
                    text="Sorry, I encountered an error while running the standup. Please try again."
                )

    def start(self) -> None:
        """Start the Slack bot."""
        logger.info("Starting Slack bot...")
        self.socket_client.connect()
        
        # Keep the bot running
        from time import sleep
        while True:
            sleep(1) 