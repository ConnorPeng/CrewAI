#!/usr/bin/env python
import sys
import warnings
from datetime import datetime
from .crew import Rhythms
from .services.github_service import GitHubService

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

import os
from dotenv import load_dotenv

load_dotenv()

def run():
    """
    Run the standup crew interactively by prompting for user input.
    """
    crew = Rhythms().standup_crew()
    result = crew.kickoff()
    return result

if __name__ == "__main__":
    run()
