from typing import Dict, List, Optional
import logging
import requests
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
        self.api_url = "https://api.linear.app/graphql"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": self.linear_token  # Use API key directly without Bearer prefix
        }

    def _execute_query(self, query: str, variables: Optional[Dict] = None) -> Dict:
        """Execute a GraphQL query against Linear API."""
        try:
            payload = {"query": query}
            if variables:
                payload["variables"] = variables
            
            logger.debug(f"Request URL: {self.api_url}")
            logger.debug(f"Request headers: {self.headers}")
            logger.debug(f"Request payload: {payload}")
            
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload
            )
            
            # Get response content before checking status
            try:
                response_json = response.json()
                if "errors" in response_json:
                    errors = response_json["errors"]
                    error_msg = "; ".join(error.get("message", str(error)) for error in errors)
                    logger.error(f"GraphQL errors: {error_msg}")
                    raise Exception(f"GraphQL errors: {error_msg}")
            except ValueError:
                logger.error(f"Invalid JSON response: {response.content}")
                response.raise_for_status()
            
            response.raise_for_status()
            return response_json
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error executing Linear API query: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_details = e.response.json()
                    logger.error(f"Response error details: {error_details}")
                except:
                    logger.error(f"Raw response content: {e.response.content}")
            raise

    def get_user_activity(self, days: int = 1) -> Dict:
        """
        Fetch user's Linear activity.
        Returns activity categorized by type (completed, in_progress, blockers).
        """
        try:
            # GraphQL query to get assigned issues without time filtering
            query = """
            query {
              viewer {
                assignedIssues(
                  first: 50
                  orderBy: updatedAt
                ) {
                  nodes {
                    id
                    title
                    identifier
                    description
                    state {
                      id
                      name
                      type
                      color
                    }
                    team {
                      id
                      name
                    }
                    url
                    completedAt
                    updatedAt
                    createdAt
                    priority
                    estimate
                    labels {
                      nodes {
                        id
                        name
                        color
                      }
                    }
                    comments {
                      nodes {
                        id
                        body
                        createdAt
                      }
                    }
                  }
                }
              }
            }
            """
            
            result = self._execute_query(query)
            
            activity = {
                "completed_work": [],
                "work_in_progress": [],
                "blockers": []
            }

            if result.get("data", {}).get("viewer", {}).get("assignedIssues", {}).get("nodes"):
                for issue in result["data"]["viewer"]["assignedIssues"]["nodes"]:
                    issue_data = {
                        "title": issue["title"],
                        "identifier": issue["identifier"],
                        "description": issue["description"],
                        "url": issue["url"],
                        "type": "issue",
                        "status": issue["state"]["name"],
                        "state_type": issue["state"]["type"],
                        "team": issue["team"]["name"] if issue.get("team") else None,
                        "priority": issue.get("priority"),
                        "estimate": issue.get("estimate"),
                        "created_at": issue["createdAt"],
                        "last_updated": issue["updatedAt"],
                        "completed_at": issue.get("completedAt"),
                        "labels": [{"name": label["name"], "color": label["color"]} 
                                 for label in issue.get("labels", {}).get("nodes", [])]
                    }

                    state_name = issue["state"]["name"].lower()
                    state_type = issue["state"]["type"]
                    labels = [label["name"].lower() for label in issue.get("labels", {}).get("nodes", [])]

                    # Categorize based on state and labels
                    if issue["completedAt"]:
                        activity["completed_work"].append(issue_data)
                    elif (state_type == "CANCELED" or 
                          state_name in ["blocked", "on hold"] or 
                          any(label in ["blocked", "blocker"] for label in labels)):
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