from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.tools import tool
from typing import Dict, List, Optional
from datetime import datetime
import logging
from src.rhythms.services.github_service import GitHubService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@CrewBase
class Rhythms():
    @tool("github_activity")
    def get_github_activity(user_id: str) -> Dict:
        """Fetches GitHub activity for a given user using a personal access token."""
        github_service = GitHubService()
        activity = github_service.get_user_activity(user_id, 5)
        summary = github_service.summarize_activity(activity)
        print("github summary", summary)
        return summary

    @agent
    def github_activity_agent(self) -> Agent:
        """GitHub analytics expert for processing activity data."""
        return Agent(
            config=self.agents_config['github_activity_agent'],
            verbose=True,
            allow_delegation=False,
            tools=[self.get_github_activity]
        )

    @agent
    def draft_agent(self) -> Agent:
        """Technical writer for creating standup summaries."""
        return Agent(
            config=self.agents_config['draft_agent'],
            verbose=True,
            allow_delegation=True,
            tools=[]
        )

    @agent
    def user_update_agent(self) -> Agent:
        """Expert facilitator for gathering standup updates."""
        return Agent(
            config=self.agents_config['user_update_agent'],
            verbose=True,
            allow_delegation=False,
            tools=[],
        )

    @task
    def fetch_github_activity(self) -> Task:
        """Fetches and analyzes recent GitHub activity."""
        logger.info("Creating Fetch GitHub Activity task")
        task = Task(
            config=self.tasks_config['fetch_github_activity_task'],
        )
        logger.info("Fetch GitHub Activity task created successfully")
        return task

    @task
    def draft_standup_update(self) -> Task:
        """Creates initial standup draft from GitHub data."""
        logger.info("Creating Draft Standup Update task")
        task = Task(
            config=self.tasks_config['draft_standup_update_task'],
            context=[self.fetch_github_activity()],
        )
        logger.info("Draft Standup Update task created successfully")
        return task

    @task
    def collect_user_update(self) -> Task:
        """Refines standup draft through user interaction."""
        logger.info("Creating Collect User Update task")
        task = Task(
            config=self.tasks_config['collect_user_update_task'],
            context=[self.draft_standup_update()],
            human_input=True,
            output_file="final_standup.md"
        )
        logger.info("Collect User Update task created successfully")
        return task

    @crew
    def standup_crew(self) -> Crew:
        """Creates an intelligent autonomous Standup crew."""
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
                self.collect_user_update()
            ],
            process=Process.sequential,
            memory=True,
            verbose=True
        )
        logger.info("Standup crew created successfully")
        return crew
