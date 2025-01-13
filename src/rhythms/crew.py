from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.tools import tool, BaseTool
from typing import Dict, List, Optional, Union, Callable
from datetime import datetime, timedelta
import logging
from src.rhythms.services.github_service import GitHubService
from src.rhythms.services.linear_service import LinearService
from src.rhythms.services.memory_service import MemoryService, StandupItemType
from crewai.agents.parser import AgentFinish
import os
from dotenv import load_dotenv

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
    
class MemoryContextTool(BaseTool):
    name: str = "get_memory_context"
    description: str = "Fetches previous plans and unresolved blockers from memory."
    get_memory_context_fn: Optional[Callable[[str], Dict]] = None

    def __init__(self, get_memory_context_fn: Callable[[str], Dict]):
        super().__init__()
        self.get_memory_context_fn = get_memory_context_fn
        load_dotenv()

    def _run(self, _: str = None) -> Dict:
        """Fetches previous plans and unresolved blockers from memory."""
        github_username = os.getenv('GITHUB_USERNAME', 'ConnorPeng')
        logger.info(f"Fetching memory context for user: {github_username}")
        if not self.get_memory_context_fn:
            return {}
        return self.get_memory_context_fn(github_username)
        
@CrewBase
class Rhythms():
    def __init__(self, slack_interaction_callback=None, slack_output_callback=None, db_path: str = "memory.db"):
        super().__init__()
        self.slack_interaction_callback = slack_interaction_callback
        self.slack_output_callback = slack_output_callback
        self.memory_service = MemoryService(db_path=db_path)
        # Disable default printing to terminal more aggressively
        logging.getLogger('crewai').setLevel(logging.ERROR)
        logging.getLogger('langchain').setLevel(logging.ERROR)
        logging.getLogger('openai').setLevel(logging.ERROR)

    def _get_memory_context(self, github_username: str) -> Dict:
        """Get context from memory including previous plans and unresolved blockers."""
        try:
            user_data = self.memory_service.get_user(github_username)
            if not user_data:
                logger.warning(f"User {github_username} not found in database")
                return {}
            
            # Get unresolved blockers
            blockers = self.memory_service.get_unresolved_blockers(user_data['id'])
            
            # Get recent standups to find previous day's plans
            recent_standups = self.memory_service.get_recent_standups(user_data['id'], days=2)
            previous_plans = []
            if recent_standups:
                for standup in recent_standups:
                    if standup['plans']:
                        previous_plans = [item['description'] for item in standup['plans']]
                        break
            
            return {
                'previous_plans': previous_plans,
                'unresolved_blockers': [blocker['description'] for blocker in blockers]
            }
        except Exception as e:
            logger.error(f"Error getting memory context: {e}")
            return {}

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

    def _store_standup_update(self, github_username: str, standup_content: str):
        """Store the finalized standup update in the database."""
        try:
            logger.info(f"connor debugging here 3 message output {standup_content}")
            # Get or create user
            user_data = self.memory_service.get_user(github_username)
            if not user_data:
                logger.warning(f"User {github_username} not found in database")
                return
            
            user_id = user_data['id']
            today = datetime.now().date().isoformat()
            logger.info(f"connor debugging here 4 message output {today}")
            # Create standup entry
            try:
                standup_id = self.memory_service.create_standup(user_id, today)
            except Exception as e:
                logger.error(f"Error creating standup: {e}")
                return
            logger.info(f"connor debugging here 5 message output {standup_id}")
            # Parse and store standup items
            sections = {
                'accomplishments': StandupItemType.ACCOMPLISHMENT,
                'blockers': StandupItemType.BLOCKER,
                'plans': StandupItemType.PLAN
            }
            logger.info(f"connor debugging here 6 message output {sections}")
            current_section = None
            items = []
            
            for line in standup_content.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Check for section headers
                lower_line = line.lower()
                for section in sections:
                    if section in lower_line:
                        current_section = section
                        break
                
                # Store items under current section
                if current_section and line.startswith('-'):
                    item = line[1:].strip()
                    if item:
                        try:
                            self.memory_service.add_standup_item(
                                standup_id,
                                sections[current_section],
                                item
                            )
                        except Exception as e:
                            logger.error(f"Error adding standup item: {e}")
            
            # Mark standup as submitted
            self.memory_service.submit_standup(standup_id)
            logger.info(f"connor debugging here 7 message output {standup_id}")
        except Exception as e:
            logger.error(f"Error storing standup update: {e}")

    @tool("github_activity")
    def get_github_activity() -> Dict:
        """Fetches GitHub activity for a given user using a personal access token."""
        github_service = GitHubService()
        activity = github_service.get_user_activity("ConnorPeng", 1)  # Get last 24 hours
        summary = github_service.summarize_activity(activity)
        logger.info(f"GitHub activity summary: {summary}")
        return {
            "completed_work": summary["completed"],
            "work_in_progress": summary["in_progress"],
            "blockers": summary["blockers"]
        }

    @tool("linear_activity")
    def get_linear_activity() -> Dict:
        """Fetches Linear activity for the authenticated user."""
        linear_service = LinearService()
        activity = linear_service.get_user_activity(1)
        logger.info(f"connor debugging here 8 message output {activity}")
        summary = linear_service.summarize_activity(activity)
        logger.info(f"connor debugging here 9 message output {summary}")
        return summary

    @agent
    def github_activity_agent(self) -> Agent:
        """GitHub analytics expert for processing activity data."""
        return Agent(
            config=self.agents_config['github_activity_agent'],
            verbose=True,
            allow_delegation=False,
            tools=[self.get_github_activity],
        )

    @agent
    def linear_activity_agent(self) -> Agent:
        """Linear analytics expert for processing activity data."""
        return Agent(
            config=self.agents_config['linear_activity_agent'],
            verbose=True,
            allow_delegation=False,
            tools=[self.get_linear_activity],
        )

    @agent
    def draft_agent(self) -> Agent:
        """Technical writer for creating standup summaries."""
        memory_tool = MemoryContextTool(self._get_memory_context)
        return Agent(
            config=self.agents_config['draft_agent'],
            verbose=True,
            allow_delegation=True,
            tools=[memory_tool],
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
            step_callback=lambda msg: self._handle_output_and_store(msg, "user_update_agent")
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
    def fetch_linear_activity(self) -> Task:
        """Fetches and analyzes recent Linear activity."""
        logger.info("Creating Fetch Linear Activity task")
        task = Task(
            config=self.tasks_config['fetch_linear_activity_task'],
        )
        logger.info("Fetch Linear Activity task created successfully")
        return task

    @task
    def draft_standup_update(self) -> Task:
        """Creates initial standup draft from GitHub data, Linear data and memory context."""
        logger.info("Creating Draft Standup Update task")
        task = Task(
            config=self.tasks_config['draft_standup_update_task'],
            context=[self.fetch_github_activity(), self.fetch_linear_activity()],
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
            step_callback=lambda msg: self._handle_output_and_store(msg, "user_update_agent"),
            output_file="final_standup.md",
            timeout=300
        )
        logger.info("Collect User Update task created successfully")
        return task

    def _handle_output_and_store(self, message: Union[str, AgentFinish], agent_name: Optional[str] = None) -> None:
        """Handle output and store standup if it's the final version."""
        logger.info(f"connor debugging here Message type: {type(message)} final message debugging here {message}")
        self._handle_output(message, agent_name)
        if isinstance(message, AgentFinish):
            # Store the finalized standup
            logger.info(f"connor debugging here 2 message output {message.output}")
            self._store_standup_update("ConnorPeng", message.output)

    @crew
    def standup_crew(self) -> Crew:
        """Creates an intelligent autonomous Standup crew."""
        logger.info("Creating Standup crew")
        crew = Crew(
            agents=[
                self.github_activity_agent(),
                self.linear_activity_agent(),
                self.draft_agent(),
                self.user_update_agent()
            ],
            tasks=[
                self.fetch_github_activity(),
                self.fetch_linear_activity(),
                self.draft_standup_update(),
                self.collect_user_update()
            ],
            process=Process.sequential,
            memory=True,
            verbose=True,
        )
        logger.info("Standup crew created successfully")
        return crew
