from datetime import datetime, time, timedelta
from src.rhythms.services.memory_service import MemoryService, StandupItemType

def create_test_data():
    """Create test data for the memory service."""
    memory_service = MemoryService(db_path="test_memory.db")

    # Create test users
    users = [
        {
            "github_username": "testuser1",
            "github_token": "ghp_test1token123",
            "email": "test1@example.com",
            "linear_token": "lin_test1token123",
            "format": "bullets",
            "timezone": "America/New_York",
            "notification_time": time(9, 30)
        },
        {
            "github_username": "testuser2",
            "github_token": "ghp_test2token456",
            "email": "test2@example.com",
            "timezone": "UTC",
            "notification_time": time(10, 0)
        }
    ]

    user_ids = []
    for user in users:
        try:
            user_id = memory_service.create_user(**user)
            user_ids.append(user_id)
            print(f"Created user {user['github_username']} with ID {user_id}")
        except Exception as e:
            print(f"Error creating user {user['github_username']}: {e}")

    # Create standups for the past week for each user
    today = datetime.now().date()
    for user_id in user_ids:
        for days_ago in range(7):
            date = (today - timedelta(days=days_ago)).isoformat()
            try:
                standup_id = memory_service.create_standup(user_id, date)
                print(f"Created standup for user {user_id} on {date}")

                # Add accomplishments
                memory_service.add_standup_item(
                    standup_id,
                    StandupItemType.ACCOMPLISHMENT,
                    f"Completed feature XYZ-{days_ago}",
                )
                memory_service.add_standup_item(
                    standup_id,
                    StandupItemType.ACCOMPLISHMENT,
                    f"Fixed bug ABC-{days_ago}",
                )

                # Add plans
                memory_service.add_standup_item(
                    standup_id,
                    StandupItemType.PLAN,
                    f"Work on feature DEF-{days_ago}",
                )
                memory_service.add_standup_item(
                    standup_id,
                    StandupItemType.PLAN,
                    f"Review PR #{100 + days_ago}",
                )

                # Add blockers (some resolved, some not)
                memory_service.add_standup_item(
                    standup_id,
                    StandupItemType.BLOCKER,
                    f"Waiting for API access from team {days_ago}",
                    resolved=(days_ago > 3)  # Resolve older blockers
                )

                # Mark older standups as submitted
                if days_ago > 0:
                    memory_service.submit_standup(standup_id)

            except Exception as e:
                print(f"Error creating standup for user {user_id} on {date}: {e}")

    # Update some user preferences
    try:
        memory_service.update_user_preferences(user_ids[0], {
            "format": "markdown",
            "notification_time": time(9, 0).strftime("%H:%M:%S")
        })
        print(f"Updated preferences for user {user_ids[0]}")
    except Exception as e:
        print(f"Error updating preferences: {e}")

    # Verify data
    print("\nVerifying data:")
    for user_id in user_ids:
        user = memory_service.get_user_by_id(user_id)
        if user:
            print(f"\nUser: {user['github_username']}")
            
            # Get recent standups
            standups = memory_service.get_recent_standups(user_id)
            print(f"Recent standups: {len(standups)}")
            
            # Get unresolved blockers
            blockers = memory_service.get_unresolved_blockers(user_id)
            print(f"Unresolved blockers: {len(blockers)}")

if __name__ == "__main__":
    create_test_data() 