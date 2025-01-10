from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.tools import tool, BaseTool
from typing import Dict, List, Optional, Union, Callable
from datetime import datetime
import logging
from src.rhythms.services.github_service import GitHubService
from crewai.agents.parser import AgentFinish

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SlackInputTool(BaseTool):
    name: str = "get_slack_input"
    description: str = "Gets input from the user through Slack."
    slack_interaction_callback: Optional[Callable[[str], str]] = None

    def __init__(self, slack_interaction_callback: Optional[Callable[[str], str]] = None):
        super().__init__()
        self.slack_interaction_callback = slack_interaction_callback

    def _run(self, prompt: str) -> str:
        logger.info(f"Running SlackInputTool with prompt: {prompt}")
        if self.slack_interaction_callback:
            return self.slack_interaction_callback(prompt)
        return "No Slack interaction callback configured"

@CrewBase
class Rhythms():
    def __init__(self, slack_interaction_callback=None, slack_output_callback=None):
        super().__init__()
        self.slack_interaction_callback = slack_interaction_callback
        self.slack_output_callback = slack_output_callback
        # Disable default printing to terminal more aggressively
        logging.getLogger('crewai').setLevel(logging.ERROR)
        logging.getLogger('langchain').setLevel(logging.ERROR)
        logging.getLogger('openai').setLevel(logging.ERROR)

    def _handle_output(self, message: Union[str, AgentFinish], agent_name: Optional[str] = None) -> None:
        """Handle output by sending to Slack if callback exists."""
        # Add guard against None messages
        if message is None:
            return
        
        try:
            if isinstance(message, AgentFinish):
                output_text = message.output
                logger.info(f"Handling AgentFinish output from {agent_name}: {output_text}")
                if self.slack_output_callback:
                    self.slack_output_callback(output_text)
            elif isinstance(message, str):
                logger.info(f"Handling string output from {agent_name}: {message}")
                if self.slack_output_callback:
                    self.slack_output_callback(message)
        except Exception as e:
            logger.error(f"Error in _handle_output: {str(e)}")

    @tool("github_activity")
    def get_github_activity() -> Dict:
        """Fetches GitHub activity for a given user using a personal access token."""
        github_service = GitHubService()
        activity = github_service.get_user_activity("ConnorPeng", 5)
        summary = github_service.summarize_activity(activity)
        return summary

    @agent
    def github_activity_agent(self) -> Agent:
        """GitHub analytics expert for processing activity data."""
        return Agent(
            config=self.agents_config['github_activity_agent'],
            verbose=True,
            allow_delegation=False,
            tools=[self.get_github_activity],
            step_callback=lambda msg: self._handle_output(msg, "user_update_agent")
        )

    @agent
    def draft_agent(self) -> Agent:
        """Technical writer for creating standup summaries."""
        return Agent(
            config=self.agents_config['draft_agent'],
            verbose=True,
            allow_delegation=True,
            tools=[],
        )

    @agent
    def user_update_agent(self) -> Agent:
        """Expert facilitator for gathering standup updates."""
        slack_tool = SlackInputTool(self.slack_interaction_callback)
        return Agent(
            config=self.agents_config['user_update_agent'],
            verbose=True,
            allow_delegation=False,
            tools=[slack_tool],
            step_callback=lambda msg: self._handle_output(msg, "user_update_agent")
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
            step_callback=lambda msg: self._handle_output(msg, "user_update_agent"),
            output_file="final_standup.md",
            timeout=300
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
            verbose=True,
        )
        logger.info("Standup crew created successfully")
        return crew
