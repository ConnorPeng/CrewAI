import os
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from github import Github, GithubException
import yaml
from dotenv import load_dotenv

class GitHubService:
    def __init__(self):
        """Initialize GitHub service with configuration"""
        load_dotenv()
        self.config = self._load_config()
        self.client = self._init_client()
        
    def _load_config(self) -> Dict:
        """Load GitHub configuration from yaml file"""
        config_path = "src/rhythms/config/github_config.yaml"
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        print("config", config)
        return config['github']
    
    def _init_client(self) -> Github:
        """Initialize GitHub client with token from environment"""
        token_env_var = self.config['token_env_var']
        token = os.getenv(token_env_var)
        if not token:
            raise ValueError(f"GitHub token not found in environment variable {token_env_var}")
        return Github(token)
    
    def get_user_activity(self, username: str = None, days: int = None) -> Dict:
        """Get GitHub activity for a user over specified number of days"""
        if username is None:
            username = os.getenv('GITHUB_USERNAME')
            if not username:
                raise ValueError("GitHub username not found in environment variables")
            
        if days is None:
            days = self.config['activity_lookback_days']
            
        since = datetime.now(timezone.utc) - timedelta(days=days)
        
        try:
            user = self.client.get_user(username)
            activity = {
                'commits': [],
                'pull_requests': [],
                'reviews': [],
                'issues': []
            }
            
            # Get all repositories including public ones
            repos = list(user.get_repos())
            print(f"Found {len(repos)} repositories for user")
            
            for repo in repos:
                try:
                    print(f"Processing repo: {repo.full_name}")
                    
                    # Get commits with error handling
                    if 'commits' in self.config['activity_types']:
                        try:
                            commits = list(repo.get_commits(author=username, since=since))
                            for commit in commits[:self.config['max_items_per_type']]:
                                activity['commits'].append({
                                    'repo': repo.full_name,
                                    'sha': commit.sha,
                                    'message': commit.commit.message,
                                    'date': commit.commit.author.date.isoformat(),
                                    'url': commit.html_url
                                })
                        except GithubException as e:
                            print(f"Error fetching commits for {repo.full_name}: {str(e)}")
                    
                    # Get pull requests with error handling
                    if 'pull_requests' in self.config['activity_types']:
                        try:
                            pulls = list(repo.get_pulls(state='all'))
                            user_pulls = [pr for pr in pulls if pr.user and pr.user.login == username]
                            for pr in user_pulls[:self.config['max_items_per_type']]:
                                if pr.created_at >= since:
                                    activity['pull_requests'].append({
                                        'repo': repo.full_name,
                                        'number': pr.number,
                                        'title': pr.title,
                                        'state': pr.state,
                                        'date': pr.created_at.isoformat(),
                                        'url': pr.html_url,
                                        'labels': [label.name for label in pr.labels]
                                    })
                        except GithubException as e:
                            print(f"Error fetching PRs for {repo.full_name}: {str(e)}")
                    
                    # Get issues
                    if 'issues' in self.config['activity_types']:
                        try:
                            issues = list(repo.get_issues(state='all'))
                            user_issues = [issue for issue in issues if issue.user and issue.user.login == username]
                            for issue in user_issues[:self.config['max_items_per_type']]:
                                if issue.created_at >= since:
                                    activity['issues'].append({
                                        'repo': repo.full_name,
                                        'number': issue.number,
                                        'title': issue.title,
                                        'state': issue.state,
                                        'date': issue.created_at.isoformat(),
                                        'url': issue.html_url,
                                        'labels': [label.name for label in issue.labels]
                                    })
                        except GithubException as e:
                            print(f"Error fetching issues for {repo.full_name}: {str(e)}")
                    
                except GithubException as e:
                    print(f"Error processing repository {repo.full_name}: {str(e)}")
                    continue
            
            return activity
            
        except GithubException as e:
            raise Exception(f"Error fetching GitHub activity: {str(e)}")

    def summarize_activity(self, activity: Dict) -> Dict:
        """
        Summarize the raw activity data into a more digestible format.
        Returns a dictionary with completed_work, work_in_progress, and blockers lists.
        """
        completed = []
        in_progress = []
        blockers = []

        # Process commits by repository
        commits_by_repo = {}
        for commit in activity.get('commits', []):
            repo = commit['repo']
            if repo not in commits_by_repo:
                commits_by_repo[repo] = []
            commits_by_repo[repo].append(commit)

        for repo, commits in commits_by_repo.items():
            commit_messages = [f"- {commit['message']}" for commit in commits]
            completed.append(
                f"Made {len(commits)} commits in {repo}:\n" + "\n".join(commit_messages)
            )

        # Process pull requests
        for pr in activity.get('pull_requests', []):
            pr_info = f"{pr['title']} ({pr['repo']}#{pr['number']}) [{pr.get('url', '')}]"
            if pr['state'] == 'closed':
                completed.append(f"Merged PR: {pr_info}")
            else:
                in_progress.append(f"Working on PR: {pr_info}")

        # Process issues
        for issue in activity.get('issues', []):
            issue_info = f"{issue['title']} ({issue['repo']}#{issue.get('number', '')}) [{issue.get('url', '')}]"
            if issue.get('state') == 'closed':
                completed.append(f"Closed issue: {issue_info}")
            elif issue.get('labels', []) and any(label.lower() in ['blocked', 'blocker'] for label in issue['labels']):
                blockers.append(f"Blocked: {issue_info}")
            else:
                in_progress.append(f"Active issue: {issue_info}")

        return {
            "completed": completed,
            "in_progress": in_progress,
            "blockers": blockers
        }