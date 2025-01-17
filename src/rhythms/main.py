#!/usr/bin/env python
import sys
import warnings
from datetime import datetime, time
from dotenv import load_dotenv
import os
import logging
import signal

# Disable verbose terminal output from dependencies
logging.getLogger('crewai').setLevel(logging.ERROR)
logging.getLogger('langchain').setLevel(logging.ERROR)
logging.getLogger('openai').setLevel(logging.ERROR)

# Fix imports to be absolute from project root
from rhythms.crew import Rhythms
from rhythms.services.github_service import GitHubService
from rhythms.services.slack_service import SlackBot
from rhythms.services.memory_service import MemoryService
from rhythms.services.scheduler_service import SchedulerService

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# Global variables
slack_bot = None
scheduler = None

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logging.info(f"Received signal {signum}")
    if slack_bot:
        logging.info("Cleaning up Slack bot...")
        slack_bot.cleanup()
    sys.exit(0)

def initialize_user(memory_service: MemoryService, github_username: str, github_token: str, email: str) -> int:
    """Initialize or retrieve user in the database."""
    try:
        # Check if user exists
        user_data = memory_service.get_user(github_username)
        if user_data:
            return user_data['id']
        
        # Create new user if doesn't exist
        user_id = memory_service.create_user(
            github_username=github_username,
            github_token=github_token,
            email=email,
            timezone="UTC",  # Default timezone
            notification_time=time(9, 0)  # Default notification time
        )
        return user_id
    except Exception as e:
        logging.error(f"Error initializing user: {e}")
        raise

def run():
    global slack_bot, scheduler
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Load environment variables
    load_dotenv()
    
    # Initialize services
    github_service = GitHubService()
    memory_service = MemoryService()
    
    try:
        # Initialize user data
        github_username = os.getenv("GITHUB_USERNAME", "ConnorPeng")
        github_token = os.getenv("GITHUB_TOKEN")
        email = os.getenv("USER_EMAIL", "default@example.com")
        notification_time = os.getenv("STANDUP_NOTIFICATION_TIME", "10:00")
        slack_channel = os.getenv("SLACK_CHANNEL_ID")
        slack_user_id = os.getenv("SLACK_USER_ID")
        if not all([github_token, slack_channel]):
            raise ValueError("GITHUB_TOKEN and SLACK_CHANNEL_ID environment variables are required")
        
        # Initialize or retrieve user
        user_id = initialize_user(memory_service, github_username, github_token, email)
        logging.info(f"Initialized user {github_username} with ID {user_id}")
        
        # Initialize Slack bot
        slack_bot = SlackBot(github_service)
        
        # Initialize scheduler with Slack bot reference
        scheduler = SchedulerService(slack_bot)
        
        # Schedule standup for the user
        scheduler.schedule_standup(slack_user_id, slack_channel, notification_time)

        # Connect scheduler to slack bot
        slack_bot.set_scheduler(scheduler)
        
        # Start the Slack bot (this will also handle scheduling)
        slack_bot.start()
        
    except Exception as e:
        if slack_bot:
            slack_bot.cleanup()
        print(f"Error starting application: {str(e)}")
        raise

if __name__ == "__main__":
    run()
