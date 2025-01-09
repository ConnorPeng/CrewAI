import os
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from github import Github, GithubException
import yaml

class GitHubService:
    def __init__(self):
        """Initialize GitHub service with configuration"""
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
        token = self.config['token_env_var']
        print("config path", self.config)
        if not token:
            raise ValueError(f"GitHub token not found in environment variable {self.config['token_env_var']}")
        return Github(token)
    
    def get_user_activity(self, username: str, days: int = None) -> Dict:
    
        if days is None:
            days = self.config['activity_lookback_days']
            
        since = datetime.now(timezone.utc) - timedelta(days=days)
        
        try:
            user = self.client.get_user("ConnorPeng")
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
                    print(f"Processing repo: {repo}")
                    
                    # Get commits with error handling
                    if 'commits' in self.config['activity_types']:
                        try:
                            commits = list(repo.get_commits(author=username, since=since))
                            for commit in commits[:self.config['max_items_per_type']]:
                                activity['commits'].append({
                                    'repo': repo.full_name,  # Using full_name instead of name
                                    'sha': commit.sha,
                                    'message': commit.commit.message,
                                    'date': commit.commit.author.date.isoformat()
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
                                        'date': pr.created_at.isoformat()
                                    })
                        except GithubException as e:
                            print(f"Error fetching PRs for {repo.full_name}: {str(e)}")
                    
                    # Similar error handling for reviews and issues...
                    
                except GithubException as e:
                    print(f"Error processing repository {repo.full_name}: {str(e)}")
                    continue
            
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
