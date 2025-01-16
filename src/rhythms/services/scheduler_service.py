import schedule
import time
import logging
from datetime import datetime
from typing import Callable, Dict, Any
from ..crew import Rhythms, SlackInputTool
from crewai.tasks import TaskOutput

# Configure logging with more detailed format
logger = logging.getLogger(__name__)

class SchedulerService:
    def __init__(self, slack_bot):
        """Initialize the scheduler service with a reference to the slack bot."""
        self.slack_bot = slack_bot
        self.jobs = {}
        logger.info("=== Initializing Scheduler Service ===")
        logger.info(f"Current time: {datetime.now()}")
        logger.info(f"System timezone: {datetime.now().astimezone().tzinfo}")

    def schedule_standup(self, user_id: str, channel_id: str, notification_time: str = "10:00"):
        """Schedule a daily standup notification for a user at a specific time."""
        logger.info("\n=== Scheduling New Standup ===")
        logger.info(f"User ID: {user_id}")
        logger.info(f"Channel ID: {channel_id}")
        logger.info(f"Notification Time: {notification_time}")
        logger.info(f"Current Jobs: {len(self.jobs)}")
        
        def prepare_and_notify():
            try:
                logger.info("\n=== Executing Scheduled Standup ===")
                logger.info(f"Time: {datetime.now()}")
                logger.info(f"User: {user_id}")
                logger.info("Initializing Rhythms with callbacks...")

                # Initialize Rhythms with callbacks
                rhythms = Rhythms(
                    slack_interaction_callback=lambda prompt: self.slack_bot._get_user_input(
                        channel_id, user_id, prompt, thread_ts if 'thread_ts' in locals() else None
                    ),
                    slack_output_callback=lambda msg: self.slack_bot._send_to_slack(
                        channel_id,
                        self.slack_bot._format_dict_for_slack(msg) if isinstance(msg, dict) else str(msg),
                        thread_ts if 'thread_ts' in locals() else None
                    )
                )

                logger.info("Creating standup crew...")
                # Create and run the crew with only the first three agents
                standup_crew = rhythms.standup_crew()
                logger.info(f"Initial crew tasks: {[t.name for t in standup_crew.tasks]}")
                
                # Keep all tasks but mark which ones to run
                draft_tasks = standup_crew.tasks[:3]  # First three tasks for draft
                user_update_task = standup_crew.tasks[3]  # Save user_update task for later
                logger.info(f"User update task name: {user_update_task.name}")
                standup_crew.tasks = draft_tasks
                
                logger.info(f"Running draft with {len(standup_crew.tasks)} tasks")
                
                # Run the crew to prepare the draft
                logger.info("Starting crew execution...")
                result = standup_crew.kickoff()
                logger.info("Crew execution completed")
                
                if result:
                    logger.info("Sending standup notification...")
                    # Start a new thread for the standup
                    response = self.slack_bot.client.chat_postMessage(
                        channel=channel_id,
                        text=f"Good morning <@{user_id}>! Time for your daily standup.",
                        blocks=[
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"Good morning <@{user_id}>! Time for your daily standup.\nI've prepared a draft based on your recent activity:"
                                }
                            }
                        ],
                        link_names=True  # Ensure user mentions are properly linked
                    )
                    thread_ts = response['ts']
                    logger.info(f"Created new thread: {thread_ts}")
                    
                    # Send the draft in the thread
                    formatted_result = (
                        self.slack_bot._format_dict_for_slack(result)
                        if isinstance(result, dict)
                        else str(result)
                    )
                    self.slack_bot._send_to_slack(
                        channel_id,
                        f"{formatted_result}\n\nPlease review and let me know if you'd like to make any changes.",
                        thread_ts
                    )
                    logger.info("Draft sent to user")
                    
                    # Save the state for the user_update_agent to continue from
                    logger.info("Saving conversation state...")
                    rhythms.current_conversation_state = {
                        'status': 'active',
                        'thread_ts': thread_ts,
                        'channel_id': channel_id,
                        'user_id': user_id,
                        'start_time': datetime.now().isoformat(),
                        'agent_outputs': rhythms.agent_outputs,
                        'last_active_agent': 'draft_agent',  # Mark where we left off
                        'current_thread': thread_ts  # Explicitly save thread context
                    }
                    session_id = rhythms.save_conversation_state()
                    logger.info(f"Saved standup state with session ID: {session_id}")
                    
                    # Get the draft task from the original crew's tasks
                    draft_task = draft_tasks[2]  # The third task is the draft task
                    
                    # Set its output
                    draft_task.output = TaskOutput(
                        description="Draft standup update",
                        raw=result.raw if hasattr(result, 'raw') else str(result),
                        summary=formatted_result,
                        agent="draft_agent"
                    )
                    
                    # Set the draft task as context for the user update task
                    user_update_task.context = [draft_task]
                    
                    # Create and configure the slack input tool with thread context
                    slack_tool = SlackInputTool(
                        slack_interaction_callback=lambda prompt: self.slack_bot._get_user_input(
                            channel_id, user_id, prompt, thread_ts
                        )
                    )
                    
                    # Add the tool to both the task and the agent
                    user_update_task.tools = [slack_tool]
                    user_update_task.agent.tools = [slack_tool]

                    # Configure the crew to only run the user update task
                    standup_crew.tasks = [user_update_task]
                    
                    # Update the Rhythms instance callbacks to use thread context
                    rhythms.slack_interaction_callback = lambda prompt: self.slack_bot._get_user_input(
                        channel_id, user_id, prompt, thread_ts
                    )
                    rhythms.slack_output_callback = lambda msg: self.slack_bot._send_to_slack(
                        channel_id,
                        self.slack_bot._format_dict_for_slack(msg) if isinstance(msg, dict) else str(msg),
                        thread_ts
                    )
                    
                    logger.info(f"Starting user update interaction in thread {thread_ts}...")
                    logger.info(f"User update task tools: {[tool.name for tool in user_update_task.tools]}")
                    logger.info(f"User update agent tools: {[tool.name for tool in user_update_task.agent.tools]}")
                    
                    # Run the user update agent
                    try:
                        logger.info("Running user update agent...")
                        update_result = standup_crew.kickoff()
                        logger.info("User update interaction completed")
                        if update_result:
                            logger.info("Final standup update saved")
                    except Exception as e:
                        logger.error(f"Error in user update interaction: {str(e)}")
                        logger.exception("Full traceback:")
                    
                    logger.info("=== Scheduled Standup Completed Successfully ===\n")
                    
            except Exception as e:
                logger.error("\n=== Error in Scheduled Standup ===")
                logger.error(f"Time: {datetime.now()}")
                logger.error(f"User: {user_id}")
                logger.error(f"Error: {str(e)}")
                logger.exception("Full traceback:")
                self.slack_bot._send_to_slack(
                    channel_id,
                    f"⚠️ Error preparing your standup: {str(e)}",
                    None
                )

        # Schedule the job for future runs
        logger.info("Creating schedule job...")
        job = schedule.every().day.at(notification_time).do(prepare_and_notify)
        self.jobs[user_id] = job
        logger.info(f"Job scheduled successfully for {notification_time}")
        logger.info(f"Next run time: {job.next_run}")
        
        # For testing: Run immediately
        logger.info("Running initial standup immediately for testing...")
        prepare_and_notify()
        
        logger.info("=== Standup Scheduling Complete ===\n")

    def check_schedules(self):
        """Check and run any pending scheduled jobs."""
        try:
            pending_jobs = len(schedule.get_jobs())
            if pending_jobs > 0:
                logger.debug(f"Checking schedules - {pending_jobs} jobs registered")
                for job in schedule.get_jobs():
                    logger.debug(f"Next run for job: {job.next_run}")
            schedule.run_pending()
        except Exception as e:
            logger.error(f"Error checking schedules: {str(e)}")
            logger.exception("Full traceback:") 