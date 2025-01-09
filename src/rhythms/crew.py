from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import SerperDevTool
from typing import Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from .services.mock_github_service import MockGitHubService
import yaml
import os

def load_config(config_name: str) -> dict:
    config_path = os.path.join(os.path.dirname(__file__), 'config', f'{config_name}.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

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
    def __init__(self):
        self.github_service = MockGitHubService()  # Initialize GitHub service
        self.memory_store = {}  # Simple memory store for demonstration
        self.agent_config = load_config('agents')
        self.task_config = load_config('tasks')
        
    def _get_github_activity(self, user_id: str) -> Dict:
        """Get GitHub activity for the user"""
        try:
            activity = self.github_service.get_user_activity(user_id)
            return self.github_service.summarize_activity(activity)
        except Exception as e:
            print(f"Warning: Failed to fetch GitHub activity: {str(e)}")
            return {'accomplishments': [], 'ongoing_work': [], 'blockers': []}

    @agent
    def chat_manager(self) -> Agent:
        config = self.agent_config['chat_manager']
        return Agent(
            name="Chat Manager",
            role=config['role'],
            goal=config['goal'],
            backstory=config['backstory'],
            verbose=True,
            allow_delegation=True,
            tools=[SerperDevTool()]
        )

    @agent
    def activity_analyzer(self) -> Agent:
        config = self.agent_config['activity_analyzer']
        return Agent(
            name="Activity Analyzer",
            role=config['role'],
            goal=config['goal'],
            backstory=config['backstory'],
            verbose=True,
            allow_delegation=True
        )

    @agent
    def context_manager(self) -> Agent:
        config = self.agent_config['context_manager']
        return Agent(
            name="Context Manager",
            role=config['role'],
            goal=config['goal'],
            backstory=config['backstory'],
            verbose=True,
            allow_delegation=True
        )

    @task
    def start_standup(self) -> Task:
        config = self.task_config['start_standup_task']
        return Task(
            description=config['description'],
            expected_output=config['expected_output'],
            agent=self.activity_analyzer()
        )

    @task
    def analyze_activity(self) -> Task:
        config = self.task_config['analyze_activity_task']
        return Task(
            description=config['description'],
            expected_output=config['expected_output'],
            agent=self.activity_analyzer()
        )

    @task
    def process_update(self) -> Task:
        config = self.task_config['process_update_task']
        return Task(
            description=config['description'],
            expected_output=config['expected_output'],
            agent=self.context_manager()
        )

    @crew
    def standup_crew(self) -> Crew:
        """Creates an intelligent autonomous Standup crew for handling daily standups"""
        return Crew(
            agents=[
                self.activity_analyzer(),
                self.context_manager(),
                self.chat_manager()
            ],
            tasks=[
                self.start_standup(),
                self.analyze_activity(),
                self.process_update()
            ],
            process=Process.sequential
        )
