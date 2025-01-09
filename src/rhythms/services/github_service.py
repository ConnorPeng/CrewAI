import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from github import Github, GithubException
import yaml

class GitHubService:
    def __init__(self, config_path: str = None):
        """
        Initialize GitHub service with configuration
        
        Args:
            config_path (str): Path to GitHub config file
        """
        self.config = self._load_config(config_path)
        self.client = self._init_client()
        
    def _load_config(self, config_path: str) -> Dict:
        """Load GitHub configuration from yaml file"""
        if not config_path:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'config',
                'github_config.yaml'
            )
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config['github']
    
    def _init_client(self) -> Github:
        """Initialize GitHub client with token from environment"""
        token = os.getenv(self.config['token_env_var'])
        if not token:
            raise ValueError(f"GitHub token not found in environment variable {self.config['token_env_var']}")
        return Github(token)
    
    def get_user_activity(self, username: str, days: int = None) -> Dict:
        """
        Get user's GitHub activity for the specified number of days
        
        Args:
            username (str): GitHub username
            days (int): Number of days to look back (default from config)
            
        Returns:
            Dict containing activity summary by type
        """
        if days is None:
            days = self.config['activity_lookback_days']
            
        since = datetime.now() - timedelta(days=days)
        
        try:
            user = self.client.get_user(username)
            activity = {
                'commits': [],
                'pull_requests': [],
                'reviews': [],
                'issues': []
            }
            
            # Get user's repositories
            for repo in user.get_repos():
                # Get commits
                if 'commits' in self.config['activity_types']:
                    commits = repo.get_commits(author=username, since=since)
                    for commit in commits[:self.config['max_items_per_type']]:
                        activity['commits'].append({
                            'repo': repo.name,
                            'sha': commit.sha,
                            'message': commit.commit.message,
                            'date': commit.commit.author.date.isoformat()
                        })
                
                # Get pull requests
                if 'pull_requests' in self.config['activity_types']:
                    pulls = repo.get_pulls(state='all', creator=username)
                    for pr in pulls[:self.config['max_items_per_type']]:
                        if pr.created_at >= since:
                            activity['pull_requests'].append({
                                'repo': repo.name,
                                'number': pr.number,
                                'title': pr.title,
                                'state': pr.state,
                                'date': pr.created_at.isoformat()
                            })
                
                # Get reviews
                if 'reviews' in self.config['activity_types']:
                    pulls = repo.get_pulls(state='all')
                    for pr in pulls[:self.config['max_items_per_type']]:
                        if pr.created_at >= since:
                            reviews = pr.get_reviews()
                            for review in reviews:
                                if review.user.login == username:
                                    activity['reviews'].append({
                                        'repo': repo.name,
                                        'pr': pr.number,
                                        'state': review.state,
                                        'date': review.submitted_at.isoformat()
                                    })
                
                # Get issues
                if 'issues' in self.config['activity_types']:
                    issues = repo.get_issues(creator=username)
                    for issue in issues[:self.config['max_items_per_type']]:
                        if issue.created_at >= since:
                            activity['issues'].append({
                                'repo': repo.name,
                                'number': issue.number,
                                'title': issue.title,
                                'state': issue.state,
                                'date': issue.created_at.isoformat()
                            })
            
            return activity
            
        except GithubException as e:
            raise Exception(f"Error fetching GitHub activity: {str(e)}")
            
    def summarize_activity(self, activity: Dict) -> Dict:
        """
        Summarize GitHub activity into a format suitable for standup
        
        Args:
            activity (Dict): Raw activity data from get_user_activity
            
        Returns:
            Dict containing summarized activity suitable for standup
        """
        summary = {
            'accomplishments': [],
            'ongoing_work': [],
            'blockers': []
        }
        
        # Process commits
        if activity['commits']:
            commit_summary = f"Made {len(activity['commits'])} commits"
            repos = set(c['repo'] for c in activity['commits'])
            if len(repos) == 1:
                commit_summary += f" in {repos.pop()}"
            elif len(repos) > 1:
                commit_summary += f" across {len(repos)} repositories"
            summary['accomplishments'].append(commit_summary)
        
        # Process pull requests
        open_prs = [pr for pr in activity['pull_requests'] if pr['state'] == 'open']
        if open_prs:
            summary['ongoing_work'].append(
                f"Working on {len(open_prs)} open pull requests"
            )
        
        merged_prs = [pr for pr in activity['pull_requests'] if pr['state'] == 'closed']
        if merged_prs:
            summary['accomplishments'].append(
                f"Merged {len(merged_prs)} pull requests"
            )
        
        # Process reviews
        if activity['reviews']:
            summary['accomplishments'].append(
                f"Reviewed {len(activity['reviews'])} pull requests"
            )
        
        # Process issues
        open_issues = [i for i in activity['issues'] if i['state'] == 'open']
        if open_issues:
            summary['blockers'].extend(
                f"Open issue: {i['title']} ({i['repo']}#{i['number']})"
                for i in open_issues
            )
        
        return summary
