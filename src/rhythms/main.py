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

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# Global variable for the slack bot
slack_bot = None

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
    global slack_bot
    
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
        
        if not github_token:
            raise ValueError("GITHUB_TOKEN environment variable is required")
        
        # Initialize or retrieve user
        user_id = initialize_user(memory_service, github_username, github_token, email)
        logging.info(f"Initialized user {github_username} with ID {user_id}")
        
        # Initialize and start Slack bot with memory service
        slack_bot = SlackBot(github_service)
        slack_bot.start()
    except Exception as e:
        if slack_bot:
            slack_bot.cleanup()
        print(f"Error starting application: {str(e)}")
        raise

if __name__ == "__main__":
    run()
