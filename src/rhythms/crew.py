from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import SerperDevTool
from typing import Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from .services.mock_github_service import MockGitHubService

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

@CrewBase
class Rhythms():
    def __init__(self):
        self.github_service = MockGitHubService()  # Initialize GitHub service
        self.memory_store = {}  # Simple memory store for demonstration
        
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
        return Agent(
            name="Chat Manager",
            role="Manages the overall conversation flow and user interaction",
            goal="Ensure smooth communication and understanding between user and system",
            backstory="An experienced conversation facilitator that helps maintain context and clarity",
            verbose=True,
            allow_delegation=True,
            tools=[SerperDevTool()]
        )

    @agent
    def standup_initiator(self) -> Agent:
        return Agent(
            name="Standup Initiator",
            role="Initiates and manages the standup process",
            goal="Start standup sessions and gather initial context",
            backstory="An experienced scrum master that helps teams run effective standups",
            verbose=True,
            allow_delegation=True
        )

    @agent
    def activity_analyzer(self) -> Agent:
        return Agent(
            name="Activity Analyzer",
            role="Analyzes GitHub activity and creates draft updates",
            goal="Generate comprehensive activity summaries from GitHub data",
            backstory="A detail-oriented analyst that tracks and summarizes development work",
            verbose=True,
            allow_delegation=True
        )

    @agent
    def followup_specialist(self) -> Agent:
        return Agent(
            name="Followup Specialist",
            role="Asks clarifying questions and ensures updates are complete",
            goal="Ensure all updates are clear and actionable",
            backstory="An experienced coach that helps team members communicate effectively",
            verbose=True,
            allow_delegation=True
        )

    @task
    def start_standup(self) -> Task:
        return Task(
            description="""
            Initialize standup session by:
            1. Fetching recent GitHub activity
            2. Loading previous context and patterns
            3. Setting up initial standup structure
            """,
            expected_output="Initial standup context with GitHub activity data and historical patterns",
            agent=self.standup_initiator()
        )

    @task
    def analyze_activity(self) -> Task:
        return Task(
            description="""
            Analyze GitHub activity and create draft update by:
            1. Reviewing code changes, PRs, and commits
            2. Identifying potential blockers from pending reviews
            3. Creating initial draft of accomplishments and plans
            """,
            expected_output="Draft standup update with accomplishments, blockers, and plans based on activity",
            agent=self.activity_analyzer()
        )

    @task
    def process_update(self) -> Task:
        return Task(
            description="""
            Process user's update by:
            1. Analyzing completeness of update
            2. Identifying areas needing clarification
            3. Generating relevant follow-up questions
            4. Ensuring all three components (accomplishments, blockers, plans) are clear
            """,
            expected_output="Processed update with follow-up questions if needed",
            agent=self.followup_specialist()
        )

    @crew
    def standup_crew(self) -> Crew:
        """Creates an intelligent autonomous Standup crew for handling daily standups"""
        return Crew(
            agents=[
                self.standup_initiator(),
                self.activity_analyzer(),
                self.followup_specialist(),
                self.chat_manager()
            ],
            tasks=[
                self.start_standup(),
                self.analyze_activity(),
                self.process_update()
            ],
            process=Process.sequential,
            verbose=True
        )
