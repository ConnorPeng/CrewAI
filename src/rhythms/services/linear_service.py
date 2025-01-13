from typing import Dict, List, Optional
import logging
from linear_python import LinearClient, Config
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class LinearService:
    def __init__(self):
        load_dotenv()
        self.linear_token = os.getenv('LINEAR_TOKEN')
        if not self.linear_token:
            raise ValueError("LINEAR_TOKEN environment variable is not set")
        self.client = LinearClient(self.linear_token)

    def get_user_activity(self, days: int = 1) -> Dict:
        """
        Fetch user's Linear activity for the past n days.
        Returns activity categorized by type (completed, in_progress, blockers).
        """
        try:
            # Get the authenticated user
            me = self.client.viewer

            # Get assigned issues with specific filters
            assigned_issues = me.assignedIssues({
                "first": 50,  # Limit results as per API guidelines
                "orderBy": "updatedAt",  # Get most recently updated first
                "filter": {
                    "updatedAt": {
                        "gt": (datetime.now() - timedelta(days=days)).isoformat()
                    }
                }
            })

            activity = {
                "completed_work": [],
                "work_in_progress": [],
                "blockers": []
            }

            for issue in assigned_issues.nodes:
                issue_data = {
                    "title": issue.title,
                    "url": f"https://linear.app/issue/{issue.identifier}",
                    "type": "issue",
                    "status": issue.state.name,
                    "last_updated": issue.updatedAt
                }

                # Categorize based on state
                if issue.completedAt:
                    activity["completed_work"].append(issue_data)
                elif issue.state.name.lower() in ["blocked", "on hold"]:
                    activity["blockers"].append(issue_data)
                else:
                    activity["work_in_progress"].append(issue_data)

            return activity

        except Exception as e:
            logger.error(f"Error fetching Linear activity: {e}")
            return {
                "completed_work": [],
                "work_in_progress": [],
                "blockers": []
            }

    def summarize_activity(self, activity: Dict) -> Dict:
        """
        Summarize the raw activity data into a more digestible format.
        """
        return {
            "completed": [
                f"{item['title']} [{item['url']}]"
                for item in activity["completed_work"]
            ],
            "in_progress": [
                f"{item['title']} (Status: {item['status']}) [{item['url']}]"
                for item in activity["work_in_progress"]
            ],
            "blockers": [
                f"{item['title']} [{item['url']}]"
                for item in activity["blockers"]
            ]
        } 