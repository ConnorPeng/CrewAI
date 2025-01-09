from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.tools import tool
from typing import Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from .services.mock_github_service import MockGitHubService
import yaml
import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Changed to logging.INFO
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# import requests

# response = requests.post("https://telemetry.crewai.com/v1/traces", verify=False)

class StandupContext(BaseModel):
    user_id: str
    timestamp: datetime
    
    # Daily Update Components
    accomplishments: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    plans: List[str] = Field(default_factory=list)
    
    # Draft and Activity Data
    message: Optional[str] = None
    draft: Optional[Dict] = Field(default_factory=dict)
    github_activity: Optional[Dict] = Field(default_factory=dict)
    linear_activity: Optional[Dict] = Field(default_factory=dict)
    
    # Follow-up tracking
    needs_followup: bool = False
    followup_questions: List[str] = Field(default_factory=list)
    clarification_needed: List[str] = Field(default_factory=list)
    
    # Context and History
    last_update: Optional[datetime] = None
    sentiment: Optional[str] = None
    recurring_blockers: List[str] = Field(default_factory=list)
    completed_items: List[str] = Field(default_factory=list)
    communication_style: Optional[str] = None
    writing_style_preference: str = "bullets"

    def to_dict(self):
        # Convert the object to a dictionary
        data = self.dict()

        # Format the datetime objects to strings
        data['timestamp'] = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        if self.last_update:
            data['last_update'] = self.last_update.strftime("%Y-%m-%d %H:%M:%S") 
        return data

@CrewBase
class Rhythms():
    @tool("github_activity")
    def get_github_activity(user_id: str) -> Dict:
      """
      Fetches GitHub activity for a given user, including their recent commits, pull requests, and other relevant activity.
      """
      return {'accomplishments': ["Made 5 commits in last 24 hours in multiple repos"], 'ongoing_work': ["Fix ABC bug in UI"], 'blockers': ["Review 21PRs"]}

    @agent
    def chat_manager(self) -> Agent:
        agent = Agent(
          config = self.agents_config['chat_manager'],
            name="Chat Manager",
            verbose=True,
            allow_delegation=True,
            tools=[]
        )
        return agent

    @agent
    def github_activity_agent(self) -> Agent:
        agent = Agent(
           config = self.agents_config['github_activity_agent'],
            verbose=True,
            allow_delegation=False,
            tools=[self.get_github_activity]
        )
        return agent

    @agent
    def draft_agent(self) -> Agent:
        agent = Agent(
           config = self.agents_config['draft_agent'],
            verbose=True,
            allow_delegation=False,  # This agent doesn't delegate further
            tools=[]
        )
        return agent

    @task
    def collect_user_update(self) -> Task:
        """Collects the user's standup update through natural conversation."""
        logger.info("Creating Collect User Update task")
        task = Task(
            config = self.tasks_config['collect_user_update_task'],
        )
        logger.info("Collect User Update task created successfully")
        return task

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
                self.draft_agent()
            ],
            tasks=[
                self.collect_user_update(),
                self.fetch_github_activity(),
                self.draft_standup_update()
            ],
            process=Process.hierarchical,
            manager_agent=self.chat_manager()
        )
        logger.info("Standup crew created successfully")
        return crew
