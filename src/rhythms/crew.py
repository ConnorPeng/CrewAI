from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.tasks import TaskOutput
from crewai.tools import tool, BaseTool
from typing import Dict, List, Optional, Union, Callable
from datetime import datetime, timedelta
import logging
from src.rhythms.services.github_service import GitHubService
from src.rhythms.services.linear_service import LinearService
from src.rhythms.services.memory_service import MemoryService, StandupItemType
from crewai.agents.parser import AgentFinish, AgentAction
from crewai.agents.crew_agent_executor import ToolResult
import os
from dotenv import load_dotenv
import json

# Configure logging
log_filename = "logs/standup.log"  # Fixed filename
os.makedirs('logs', exist_ok=True)  # Create logs directory if it doesn't exist

# Configure logging to both file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, mode='w'),  # 'w' mode overwrites the file
        logging.StreamHandler()  # This will continue logging to console
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"Starting new logging session in: {log_filename}")

class SlackInputTool(BaseTool):
    name: str = "get_slack_input"
    description: str = "Gets input from the user through Slack. Use this tool to interact with the user and get their feedback or updates."
    slack_interaction_callback: Optional[Callable[[str], str]] = None

    def __init__(self, slack_interaction_callback: Optional[Callable[[str], str]] = None):
        """Initialize the tool with a callback for Slack interaction."""
        super().__init__()
        self.slack_interaction_callback = slack_interaction_callback

    def _run(self, prompt: str) -> str:
        """Run the tool with the given prompt."""
        logger.info(f"Running SlackInputTool with prompt: {prompt}")
        if self.slack_interaction_callback:
            try:
                response = self.slack_interaction_callback(prompt)
                logger.info(f"Received response from Slack: {response}")
                return response
            except Exception as e:
                logger.error(f"Error getting Slack input: {str(e)}")
                raise
        return "No Slack interaction callback configured"

    def _arun(self, prompt: str) -> str:
        """Run the tool asynchronously (required by CrewAI)."""
        return self._run(prompt)
    
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
        self.current_conversation_state = None
        self.agent_outputs = {}  # Store outputs from each agent
        # Disable default printing to terminal more aggressively
        logging.getLogger('crewai').setLevel(logging.ERROR)
        logging.getLogger('langchain').setLevel(logging.ERROR)
        logging.getLogger('openai').setLevel(logging.ERROR)

    def save_conversation_state(self, user_id: str) -> str:
        """Save the current conversation state and return a session ID."""
        if not self.current_conversation_state:
            logger.warning("No active conversation to save")
            return None
            
        logger.info("=== Saving Conversation State ===")
        logger.info(f"Current agent outputs: {json.dumps(self.agent_outputs, indent=2)}")
        
        # Add agent outputs and progress to the state
        self.current_conversation_state.update({
            'agent_outputs': self.agent_outputs,
            'last_active_agent': self._get_last_active_agent(),
            'completed_agents': list(self.agent_outputs.keys())
        })
        
        logger.info(f"Last active agent: {self._get_last_active_agent()}")
        logger.info(f"Completed agents: {list(self.agent_outputs.keys())}")
            
        session_id = self.memory_service.save_conversation_state(
            slack_user_id=user_id,  # Pass the user_id from Slack
            state=self.current_conversation_state
        )
        logger.info(f"Saved conversation state with session ID: {session_id}")
        logger.info("=== State Save Complete ===")
        
        self.current_conversation_state = None
        self.agent_outputs = {}
        return session_id

    def _get_last_active_agent(self) -> Optional[str]:
        """Get the name of the last active agent."""
        if not self.agent_outputs:
            return None
        return list(self.agent_outputs.keys())[-1]

    def resume_conversation(self, session_id: str) -> bool:
        """Resume a previously saved conversation state."""
        try:
            logger.info("=== Resuming Conversation ===")
            logger.info(f"Attempting to resume session: {session_id}")
            
            state = self.memory_service.get_conversation_state(session_id)
            if not state:
                logger.warning(f"No saved conversation found for session ID: {session_id}")
                return False
                
            logger.info("Retrieved state from database")
            logger.info(f"State contents: {json.dumps(state, indent=2)}")
            
            self.current_conversation_state = state
            # Restore agent outputs
            self.agent_outputs = state.get('agent_outputs', {})
            logger.info(f"Restored outputs from agents: {list(self.agent_outputs.keys())}")
            logger.info("=== Resume Complete ===")
            
            return True
        except Exception as e:
            logger.error(f"Error resuming conversation: {e}")
            return False

    def _update_conversation_state(self, state: Dict) -> None:
        """Update the current conversation state."""
        self.current_conversation_state = state

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

    def _handle_output(self, agent_name: str, content: str) -> Union[str, AgentFinish]:
        """Handle output from an agent."""
        logger.info("=== Handling Output ===")
        logger.info(f"Message type: {type(content)}")
        logger.info(f"Message content: {content}")

        # Check if already finalized
        if hasattr(self, 'is_finalized') and self.is_finalized:
            logger.info("Standup already finalized, skipping further processing")
            return AgentFinish(
                thought="Standup already finalized",
                output="Standup already finalized",
                text="Standup already finalized, stopping further processing"
            )

        if isinstance(content, str):
            # If this is a draft (has sections), check if it's approved
            if any(section in content.lower() for section in ["accomplishments:", "blockers:", "plans:"]):
                # This is a draft being shown to the user
                return content
            elif "FINAL STANDUP:" in content:
                # Extract and store the final content
                final_content = content.split("FINAL STANDUP:", 1)[1].strip()
                self._store_standup_update("ConnorPeng", final_content)
                # Set finalization flag
                self.is_finalized = True
                # Stop further processing
                return AgentFinish(
                    thought="Standup finalized successfully",
                    output=final_content,
                    text="Standup finalized successfully"
                )
            else:
                # This is a user update, let the agent process it
                return content

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
            timeout=300,
            tools=[SlackInputTool(self.slack_interaction_callback)],
            agent=self.user_update_agent()
        )
        logger.info("Collect User Update task created successfully")
        return task

    def _handle_output_and_store(self, message: Union[str, AgentFinish], agent_name: Optional[str] = None) -> None:
        """Handle output and store standup if it's the final version."""
        logger.info(f"=== Handling Output and Store ===")
        logger.info(f"Message type: {type(message)}")
        logger.info(f"Message content: {message}")
        
        # Extract the actual content
        content = None
        if isinstance(message, AgentFinish):
            content = message.return_values.get('output') if hasattr(message, 'return_values') else message.output
            logger.info(f"Extracted content from AgentFinish: {content}")
        elif isinstance(message, AgentAction):
            # Handle AgentAction - extract tool call information
            if message.tool == "get_slack_input":
                content = message.tool_input
                logger.info(f"Extracted content from AgentAction tool input: {content}")
            else:
                content = message.text
                logger.info(f"Extracted content from AgentAction text: {content}")
        elif isinstance(message, ToolResult):  # Handle ToolResult
            content = message.result
            logger.info(f"Extracted content from ToolResult: {content}")
        elif isinstance(message, str):
            content = message
            logger.info(f"Using string content directly: {content}")
        elif isinstance(message, dict):
            content = message.get('output', str(message))
            logger.info(f"Extracted content from dict: {content}")
            
        if not content:
            logger.warning("No content extracted from message")
            return
            
        # First handle the output
        output_result = self._handle_output(agent_name, content)
        if isinstance(output_result, AgentFinish):
            # If we got an AgentFinish, we're done
            logger.info("Received AgentFinish, ending processing")
            return output_result
        elif output_result:
            return output_result
            
        # Check if this is a final standup
        if isinstance(content, str):
            if "FINAL STANDUP:" in content:
                logger.info("Found final standup marker, storing update")
                final_content = content.split("FINAL STANDUP:", 1)[1].strip()
                self._store_standup_update("ConnorPeng", final_content)
                # Clear active standup when finished
                self.active_standup = None
            else:
                # This is a user response, pass it back to the agent for processing
                logger.info("Processing user response")
                if self.slack_interaction_callback:
                    # If the content looks like a draft (has sections), it's for user review
                    if any(section in content.lower() for section in ["accomplishments", "blockers", "plans"]):
                        response = self.slack_interaction_callback(f"{content}\nDoes this look complete?")
                    else:
                        # This is a user update, let the agent process it
                        response = content
                    logger.info(f"Got response from slack callback: {response}")
                    return response
        elif isinstance(content, dict):
            if content.get('raw') and "FINAL STANDUP:" in content['raw']:
                logger.info("Found final standup marker in raw output, storing update")
                final_content = content['raw'].split("FINAL STANDUP:", 1)[1].strip()
                self._store_standup_update("ConnorPeng", final_content)
                # Clear active standup when finished
                self.active_standup = None
            else:
                # This might be a user response in a structured format
                logger.info("Processing structured user response")
                if self.slack_interaction_callback:
                    response = self.slack_interaction_callback(content.get('raw', str(content)))
                    logger.info(f"Got response from slack callback: {response}")
                    return response

    @crew
    def standup_crew(self) -> Crew:
        """Creates an intelligent autonomous Standup crew."""
        logger.info("\n=== Creating Standup Crew ===")
        logger.info(f"Current conversation state exists: {self.current_conversation_state is not None}")
        if self.current_conversation_state:
            logger.info(f"Current conversation state contents: {json.dumps(self.current_conversation_state, indent=2)}")
        
        # Create all tasks first
        logger.info("\n=== Creating Initial Tasks ===")
        github_task = self.fetch_github_activity()
        linear_task = self.fetch_linear_activity()
        draft_task = self.draft_standup_update()
        user_update_task = self.collect_user_update()
        
        # Define task dependencies
        logger.info("\n=== Setting Up Task Dependencies ===")
        draft_task.context = [github_task, linear_task]  # Draft depends on both GitHub and Linear data
        user_update_task.context = [draft_task]  # User update depends on the draft
        logger.info(f"Draft task context: {[t.description for t in draft_task.context]}")
        logger.info(f"User update task context: {[t.description for t in user_update_task.context]}")
        
        tasks_to_include = []
        
        # If resuming from a saved state
        if self.current_conversation_state and self.current_conversation_state.get('agent_outputs'):
            logger.info("\n=== Resuming from Saved State ===")
            agent_outputs = self.current_conversation_state.get('agent_outputs', {})
            last_active_agent = self.current_conversation_state.get('last_active_agent')
            completed_agents = self.current_conversation_state.get('completed_agents', [])
            
            logger.info("\n=== Resume State Details ===")
            logger.info(f"Last active agent: {last_active_agent}")
            logger.info(f"Completed agents: {completed_agents}")
            logger.info(f"Agent outputs available: {list(agent_outputs.keys())}")
            logger.info(f"Agent outputs content: {json.dumps(agent_outputs, indent=2)}")
            
            # Map agent names to tasks
            task_mapping = {
                'github_activity_agent': github_task,
                'linear_activity_agent': linear_task,
                'draft_agent': draft_task,
                'user_update_agent': user_update_task
            }
            
            # Restore outputs to tasks
            logger.info("\n=== Restoring Task Outputs ===")
            for agent_name, output_data in agent_outputs.items():
                if agent_name in task_mapping:
                    task = task_mapping[agent_name]
                    logger.info(f"\nProcessing output for agent: {agent_name}")
                    logger.info(f"Task before restoration: has_output={hasattr(task, 'output')}")
                    
                    # Ensure we have valid output data
                    if not output_data:
                        logger.warning(f"No output data for agent {agent_name}, skipping")
                        continue
                        
                    # Create a TaskOutput object from the saved data with fallbacks
                    task_output = TaskOutput(
                        description=output_data.get('description', task.description or ''),
                        raw=output_data.get('raw', ''),
                        summary=output_data.get('summary', output_data.get('raw', '')[:100] + '...' if output_data.get('raw') else ''),
                        agent=agent_name,
                    )
                    
                    # Validate the TaskOutput object
                    if not task_output.raw and not task_output.summary:
                        logger.warning(f"Invalid TaskOutput for agent {agent_name}, skipping")
                        continue
                        
                    # Set the task output
                    task.output = task_output
                    logger.info(f"Task after restoration: has_output={hasattr(task, 'output')}")
                    logger.info(f"Restored output content: {json.dumps(output_data, indent=2)}")
                    
                    # Make the output available in the task's context
                    if task.context:
                        logger.info(f"\nProcessing context for task: {task.description}")
                        for context_task in task.context:
                            logger.info(f"Context task before: {context_task.description}, has_output={hasattr(context_task, 'output')}")
                            if not hasattr(context_task, 'output'):
                                context_task.output = task_output
                                logger.info(f"Added output to context task: {context_task.description}")
                            logger.info(f"Context task after: has_output={hasattr(context_task, 'output')}")
            
            # Determine which tasks to include based on last active agent
            logger.info("\n=== Determining Tasks to Include ===")
            should_include = False
            for agent_name, task in task_mapping.items():
                logger.info(f"\nChecking agent: {agent_name}")
                logger.info(f"Task has output: {hasattr(task, 'output')}")
                if hasattr(task, 'output'):
                    logger.info(f"Task output summary: {task.output.summary}")
                
                if agent_name == last_active_agent:
                    should_include = True
                    logger.info(f"Found last active agent: {agent_name}, will include remaining tasks")
                if should_include:
                    tasks_to_include.append(task)
                    logger.info(f"Including task: {task.description}")
                else:
                    logger.info(f"Skipping task for agent: {agent_name} (already completed)")
                    if hasattr(task, 'output'):
                        logger.info(f"Skipped task has output available: {task.output.summary}")
        else:
            # First time standup or no saved state - reset everything
            logger.info("\n=== Starting New Standup Session ===")
            logger.info("Resetting conversation state and agent outputs")
            self.current_conversation_state = {
                'start_time': datetime.now().isoformat(),
                'agent_outputs': {},
                'completed_agents': [],
                'last_active_agent': None
            }
            self.agent_outputs = {}
            tasks_to_include = [github_task, linear_task, draft_task, user_update_task]
            logger.info(f"Including all tasks: {[t.description for t in tasks_to_include]}")
        
        # Set up task callbacks before creating the crew
        logger.info("\n=== Setting Up Task Callbacks ===")
        for task in tasks_to_include:
            task.callback = lambda output, task=task: self._handle_task_completion(output, task)
            logger.info(f"Added callback for task: {task.description}")
            if hasattr(task, 'output') and task.output:
                try:
                    logger.info(f"Task already has output: {task.output.summary if hasattr(task.output, 'summary') else 'No summary available'}")
                except Exception as e:
                    logger.warning(f"Could not access task output summary: {str(e)}")
        
        logger.info(f"\nCreating crew with {len(tasks_to_include)} tasks")
        crew = Crew(
            agents=[
                self.github_activity_agent(),
                self.linear_activity_agent(),
                self.draft_agent(),
                self.user_update_agent()
            ],
            tasks=tasks_to_include,
            process=Process.sequential,
            memory=True,
            verbose=True,
            state=self.current_conversation_state
        )
        
        logger.info("\n=== Crew Creation Summary ===")
        logger.info(f"Total tasks included: {len(tasks_to_include)}")
        if tasks_to_include:
            logger.info(f"First task to execute: {tasks_to_include[0].description}")
            logger.info(f"Task sequence: {[t.description for t in tasks_to_include]}")
            logger.info("Task outputs available:")
            for task in tasks_to_include:
                try:
                    if hasattr(task, 'output') and task.output:
                        logger.info(f"- {task.description}: {task.output.summary if hasattr(task.output, 'summary') else 'No summary available'}")
                    else:
                        logger.info(f"- {task.description}: No output")
                except Exception as e:
                    logger.warning(f"Could not access task output for {task.description}: {str(e)}")
                    logger.info(f"- {task.description}: Error accessing output")
        logger.info("=== Crew Creation Complete ===")
        
        return crew

    def _handle_task_completion(self, output: 'TaskOutput', task: Task) -> None:
        """Handle task completion by updating agent outputs and completed agents."""
        logger.info(f"=== Handling Task Completion ===")
        logger.info(f"Task completed: {task.description}")
        
        # Initialize conversation state if not exists
        if not self.current_conversation_state:
            self.current_conversation_state = {
                'start_time': datetime.now().isoformat(),
                'agent_outputs': {},
                'completed_agents': [],
                'last_active_agent': None
            }
        
        if task.agent:
            # Clean up the agent role string by removing quotes and newlines
            agent_name = task.agent.role.strip().strip('"').strip("'").lower().replace(' ', '_')
            logger.info(f"Updating outputs for agent: {agent_name}")
            # Store both raw output and structured output
            self.agent_outputs[agent_name] = {
                'raw': output.raw,
                'description': output.description,
                'summary': output.summary
            }
            
            # Ensure completed_agents exists
            if 'completed_agents' not in self.current_conversation_state:
                self.current_conversation_state['completed_agents'] = []
                
            if agent_name not in self.current_conversation_state['completed_agents']:
                self.current_conversation_state['completed_agents'].append(agent_name)
            self.current_conversation_state['last_active_agent'] = agent_name
            self.current_conversation_state['agent_outputs'] = self.agent_outputs
            
            logger.info(f"Updated conversation state:")
            logger.info(f"- Task Description: {output.description}")
            logger.info(f"- Task Summary: {output.summary}")
            logger.info(f"- Completed agents: {self.current_conversation_state['completed_agents']}")
            logger.info(f"- Last active agent: {self.current_conversation_state['last_active_agent']}")
            logger.info(f"- Agent outputs count: {len(self.agent_outputs)}")
            
            # If the output has JSON or Pydantic data, log it
            if hasattr(output, 'json_dict') and output.json_dict:
                logger.info(f"- JSON Output: {json.dumps(output.json_dict, indent=2)}")
            if hasattr(output, 'pydantic') and output.pydantic:
                logger.info(f"- Pydantic Output: {output.pydantic}")
        else:
            logger.warning(f"Task has no associated agent: {task.description}")
            
        logger.info("=== Task Completion Handling Complete ===")
