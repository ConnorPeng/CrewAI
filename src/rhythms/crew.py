from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.tools import tool
from typing import Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import yaml
import os
import logging
import json
from src.rhythms.services.github_service import GitHubService

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Changed to logging.INFO
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@CrewBase
class Rhythms():
    @tool("github_activity")
    def get_github_activity(user_id: str) -> Dict:
        """
        Fetches GitHub activity for a given user using a personal access token.
        """
        github_service = GitHubService()
        activity = github_service.get_user_activity("ConnorPeng", 3)
        summary = github_service.summarize_activity(activity)
        return summary


    # @agent
    # def chat_manager(self) -> Agent:
    #     agent = Agent(
    #       config = self.agents_config['chat_manager'],
    #         name="Chat Manager",
    #         verbose=True,
    #         allow_delegation=True,
    #         tools=[]
    #     )
    #     return agent

    @agent
    def user_update_agent(self) -> Agent:
        agent = Agent(
           config = self.agents_config['user_update_agent'],
            verbose=True,
            allow_delegation=True,
            tools=[],
        )
        return agent

    @agent
    def github_activity_agent(self) -> Agent:
        agent = Agent(
           config = self.agents_config['github_activity_agent'],
            verbose=True,
            allow_delegation=True,
            tools=[self.get_github_activity]
        )
        return agent

    @agent
    def draft_agent(self) -> Agent:
        agent = Agent(
           config = self.agents_config['draft_agent'],
            verbose=True,
            allow_delegation=True,
            tools=[]
        )
        return agent

    @task
    def collect_user_update(self) -> Task:
        """Collects the user's standup update through natural conversation."""
        logger.info("Creating Collect User Update task")
        task = Task(
            config = self.tasks_config['collect_user_update_task'],
            context=[self.draft_standup_update(), self.fetch_github_activity()],
            human_input=True
        )
        logger.info("Collect User Update task created successfully")
        return task

    # @task
    # def standup_manager_task(self) -> Task:
    #     """Oversees the entire standup process by coordinating agents and tasks."""
    #     logger.info("Creating Standup Manager task")
    #     task = Task(
    #         config=self.tasks_config['standup_manager_task'],
    #         human_input=True
    #     )
    #     logger.info("Standup Manager task created successfully")
    #     return task


    @task
    def fetch_github_activity(self) -> Task:
        """Fetches and summarizes the user's GitHub activity."""
        logger.info("Creating Fetch GitHub Activity task")
        task = Task(
            config = self.tasks_config['fetch_github_activity_task'],
        )
        logger.info("Fetch GitHub Activity task created successfully")
        return task

    @task
    def draft_standup_update(self) -> Task:
        """Generates a draft standup update based on user input and GitHub activity."""
        logger.info("Creating Draft Standup Update task")
        task = Task(
            config = self.tasks_config['draft_standup_update_task'],
            context=[self.fetch_github_activity()]
        )
        logger.info("Draft Standup Update task created successfully")
        return task

    @crew
    def standup_crew(self) -> Crew:
        """Creates an intelligent autonomous Standup crew for handling daily standups."""
        logger.info("Creating Standup crew")
        crew = Crew(
            agents=[
                self.github_activity_agent(),
                self.draft_agent(),
                self.user_update_agent()
            ],
            tasks=[
                self.fetch_github_activity(),
                self.draft_standup_update(),
                self.collect_user_update(),
            ],
            process=Process.sequential,
            memory=True,
            verbose=True,
            planning=True
        )
        logger.info("Standup crew created successfully")
        return crew
