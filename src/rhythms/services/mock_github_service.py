from datetime import datetime, timedelta
from typing import Dict

class MockGitHubService:
    def __init__(self, config_path: str = None):
        """Mock GitHub service for testing"""
        self.mock_activity = {
            'commits': [
                {
                    'repo': 'test-repo',
                    'sha': '1234567890abcdef',
                    'message': 'Add new feature XYZ',
                    'date': (datetime.now() - timedelta(hours=2)).isoformat()
                },
                {
                    'repo': 'another-repo',
                    'sha': 'abcdef1234567890',
                    'message': 'Fix bug in module ABC',
                    'date': (datetime.now() - timedelta(hours=5)).isoformat()
                }
            ],
            'pull_requests': [
                {
                    'repo': 'test-repo',
                    'number': 42,
                    'title': 'Feature: Add XYZ functionality',
                    'state': 'open',
                    'date': (datetime.now() - timedelta(days=1)).isoformat()
                },
                {
                    'repo': 'test-repo',
                    'number': 41,
                    'title': 'Bugfix: Handle edge case',
                    'state': 'closed',
                    'date': (datetime.now() - timedelta(days=2)).isoformat()
                }
            ],
            'reviews': [
                {
                    'repo': 'another-repo',
                    'pr': 123,
                    'state': 'APPROVED',
                    'date': (datetime.now() - timedelta(hours=3)).isoformat()
                }
            ],
            'issues': [
                {
                    'repo': 'test-repo',
                    'number': 99,
                    'title': 'Performance degradation in production',
                    'state': 'open',
                    'date': (datetime.now() - timedelta(hours=12)).isoformat()
                }
            ]
        }

    def get_user_activity(self, username: str, days: int = None) -> Dict:
        """Mock getting user's GitHub activity"""
        return self.mock_activity

    def summarize_activity(self, activity: Dict) -> Dict:
        """
        Summarize GitHub activity into a format suitable for standup.
        This is the same implementation as the real service.
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
