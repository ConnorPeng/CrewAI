from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

class GitHubActivityInput(BaseModel):
    """Input schema for GitHubActivityTool."""
    user_id: str = Field(..., description="The user ID to fetch GitHub activity for")

class GitHubActivityTool(BaseTool):
    name: str = "github_activity"
    description: str = (
        "Fetches GitHub activity for a given user, including their recent commits, "
        "pull requests, and other relevant activity."
    )
    args_schema: Type[BaseModel] = GitHubActivityInput

    def _run(self, user_id: str) -> str:
        # This will be handled by the MockGitHubService
        # The actual implementation should be connected to your github_service
        return f"Fetched GitHub activity for user {user_id}"
