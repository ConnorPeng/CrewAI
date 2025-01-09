# src/latest_ai_development/crew.py
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import SerperDevTool
from typing import Dict, Optional
from datetime import datetime
from pydantic import BaseModel

class StandupContext(BaseModel):
    user_id: str
    timestamp: datetime
    message: Optional[str]
    draft: Optional[Dict]
    blocker_count: int = 0
    needs_followup: bool = False
    last_update: Optional[datetime]
    sentiment: Optional[str]

@CrewBase
class Rhythms():

  @agent
  def chat_manager(self) -> Agent:
    return Agent(
      config=self.agents_config['chat_manager'],
      verbose=True
    )

  @agent
  def activity_analyzer(self) -> Agent:
    return Agent(
      config=self.agents_config['activity_analyzer'],
      verbose=True
    )

  @agent
  def context_manager(self) -> Agent:
    return Agent(
      config=self.agents_config['context_manager'],
      verbose=True
    )

  @task
  def analyze_response_task(self) -> Task:
    return Task(
      config=self.tasks_config['analyze_response_task'],
      context=[{
        'input_type': 'raw_message',
        'output_type': 'analysis',
        'description': 'Analyze the raw message content',
        'expected_output': 'A detailed analysis of the message content'
      }]
    )

  @task
  def analyze_activity_task(self) -> Task:
    return Task(
      config=self.tasks_config['analyze_activity_task'],
      context=[{
        'input_type': 'context',
        'output_type': 'activity_analysis',
        'description': 'Analyze the activity context',
        'expected_output': 'A detailed analysis of the activity'
      }]
    )

  @task
  def decide_next_action_task(self) -> Task:
    return Task(
      config=self.tasks_config['decide_next_action_task'],
      context=[{
        'input_type': ['analysis', 'activity_analysis'],
        'output_type': 'decision',
        'description': 'Decide the next action based on analysis and activity',
        'expected_output': 'A decision on the next action to take'
      }]
    )

  @task
  def generate_summary_task(self) -> Task:
    return Task(
      config=self.tasks_config['generate_summary_task'],
      context=[{
        'input_type': ['analysis', 'activity_analysis', 'decision'],
        'output_type': 'summary',
        'description': 'Generate a summary based on analysis, activity, and decision',
        'expected_output': 'A summary of the analysis, activity, and decision'
      }]
    )

  @crew
  def standup_crew(self) -> Crew:
    """Creates the Standup crew for handling daily standups"""
    return Crew(
      agents=[
        self.chat_manager(),
        self.activity_analyzer(),
        self.context_manager(),
      ],
      tasks=[
        self.analyze_response_task(),
        self.analyze_activity_task(),
        self.decide_next_action_task(),
        self.generate_summary_task(),
      ],
      manager_agent=self.chat_manager(),
      process=Process.sequential,
      verbose=True
    )
