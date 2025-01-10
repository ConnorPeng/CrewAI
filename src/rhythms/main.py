#!/usr/bin/env python
import sys
import warnings
from datetime import datetime
from dotenv import load_dotenv
import os

# Fix imports to be absolute from project root
from rhythms.crew import Rhythms
from rhythms.services.github_service import GitHubService
from rhythms.services.slack_service import SlackBot

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

def run():
    # Load environment variables
    load_dotenv()
    
    # Initialize services
    github_service = GitHubService()
    
    try:
        # Initialize and start Slack bot
        slack_bot = SlackBot(github_service)
        slack_bot.start()
    except Exception as e:
        print(f"Error starting Slack bot: {str(e)}")
        raise

if __name__ == "__main__":
    run()
