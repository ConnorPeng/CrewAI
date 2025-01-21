import unittest
from datetime import datetime, time, timedelta
import os
import sqlite3
import logging

# Disable all logging during tests
logging.disable(logging.CRITICAL)

from rhythms.services.memory_service import MemoryService, StandupItemType

class TestMemoryService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        cls.test_db = "test_memory.db"
        cls.memory_service = MemoryService(db_path=cls.test_db)

    def setUp(self):
        """Reset database before each test."""
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self.memory_service = MemoryService(db_path=self.test_db)

    def tearDown(self):
        """Clean up after each test."""
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def create_test_user(self, suffix="1"):
        """Helper method to create a test user."""
        return self.memory_service.create_user(
            github_username=f"testuser{suffix}",
            github_token=f"ghp_test{suffix}token123",
            email=f"test{suffix}@example.com",
            timezone="UTC"
        )

    def test_database_initialization(self):
        """Test database is properly initialized."""
        # Connect directly to check tables
        conn = sqlite3.connect(self.test_db)
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        
        # Check tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        expected_tables = {'users', 'standups', 'standup_items'}
        self.assertEqual(expected_tables, tables & expected_tables)
        
        # Check foreign key constraints
        cursor.execute("PRAGMA foreign_keys")
        self.assertEqual(cursor.fetchone()[0], 1)
        
        # Test foreign key constraint
        cursor.execute("""
            INSERT INTO users (github_username, github_token, email)
            VALUES ('test_user', 'test_token', 'test@example.com')
        """)
        user_id = cursor.lastrowid
        
        # This should work (valid user_id)
        cursor.execute("""
            INSERT INTO standups (user_id, date)
            VALUES (?, ?)
        """, (user_id, datetime.now().date().isoformat()))
        
        # This should fail (invalid user_id)
        with self.assertRaises(sqlite3.IntegrityError) as context:
            cursor.execute("""
                INSERT INTO standups (user_id, date)
                VALUES (999, ?)
            """, (datetime.now().date().isoformat(),))
        self.assertIn("FOREIGN KEY constraint failed", str(context.exception))
        
        conn.close()

    def test_user_creation(self):
        """Test user creation with various scenarios."""
        # Test successful user creation
        user_id = self.create_test_user()
        self.assertIsNotNone(user_id)
        
        # Test all fields are properly stored
        user = self.memory_service.get_user_by_id(user_id)
        self.assertEqual(user["github_username"], "testuser1")
        self.assertEqual(user["email"], "test1@example.com")
        self.assertEqual(user["timezone"], "UTC")
        self.assertEqual(user["format"], "bullets")  # Default value
        
        # Test duplicate username
        with self.assertRaises(sqlite3.IntegrityError) as context:
            self.memory_service.create_user(
                github_username="testuser1",  # Same username
                github_token="different_token",
                email="different@example.com"
            )
        self.assertIn("UNIQUE constraint failed: users.github_username", str(context.exception))
        
        # Test duplicate email
        with self.assertRaises(sqlite3.IntegrityError) as context:
            self.memory_service.create_user(
                github_username="different_user",
                github_token="different_token",
                email="test1@example.com"  # Same email
            )
        self.assertIn("UNIQUE constraint failed: users.email", str(context.exception))

    def test_standup_lifecycle(self):
        """Test complete standup lifecycle."""
        user_id = self.create_test_user()
        today = datetime.now().date().isoformat()
        
        # Create standup
        standup_id = self.memory_service.create_standup(user_id, today)
        self.assertIsNotNone(standup_id)
        
        # Test duplicate date constraint
        with self.assertRaises(sqlite3.IntegrityError) as context:
            self.memory_service.create_standup(user_id, today)
        self.assertIn("UNIQUE constraint failed: standups.user_id, standups.date", str(context.exception))
        
        # Add items
        items = [
            (StandupItemType.ACCOMPLISHMENT, "Completed task A"),
            (StandupItemType.ACCOMPLISHMENT, "Completed task B"),
            (StandupItemType.PLAN, "Plan for tomorrow"),
            (StandupItemType.BLOCKER, "Waiting for review", False),
            (StandupItemType.BLOCKER, "System access", True)
        ]
        
        for item_type, desc, *resolved in items:
            item_id = self.memory_service.add_standup_item(
                standup_id,
                item_type,
                desc,
                resolved[0] if resolved else False
            )
            self.assertIsNotNone(item_id)
        
        # Submit standup
        self.memory_service.submit_standup(standup_id)
        
        # Verify final state
        standups = self.memory_service.get_recent_standups(user_id)
        self.assertEqual(len(standups), 1)
        
        standup = standups[0]
        self.assertEqual(standup["date"], today)
        self.assertTrue(standup["submitted"])
        self.assertEqual(len(standup["accomplishments"]), 2)
        self.assertEqual(len(standup["plans"]), 1)
        self.assertEqual(len(standup["blockers"]), 2)
        
        # Check unresolved blockers
        blockers = self.memory_service.get_unresolved_blockers(user_id)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["description"], "Waiting for review")

    def test_user_preferences(self):
        """Test user preferences management."""
        user_id = self.create_test_user()
        
        # Test default values
        user = self.memory_service.get_user_by_id(user_id)
        self.assertEqual(user["format"], "bullets")
        self.assertEqual(user["timezone"], "UTC")
        self.assertEqual(user["notification_time"], "09:00:00")
        
        # Update all preferences
        preferences = {
            "format": "markdown",
            "timezone": "America/New_York",
            "notification_time": "10:30:00"
        }
        self.memory_service.update_user_preferences(user_id, preferences)
        
        # Verify updates
        user = self.memory_service.get_user_by_id(user_id)
        for key, value in preferences.items():
            self.assertEqual(user[key], value)
        
        # Test partial update
        self.memory_service.update_user_preferences(user_id, {"format": "text"})
        user = self.memory_service.get_user_by_id(user_id)
        self.assertEqual(user["format"], "text")
        self.assertEqual(user["timezone"], "America/New_York")  # Unchanged
        
        # Test invalid fields are ignored
        self.memory_service.update_user_preferences(user_id, {
            "format": "json",
            "invalid_field": "value"
        })
        user = self.memory_service.get_user_by_id(user_id)
        self.assertEqual(user["format"], "json")
        self.assertNotIn("invalid_field", user)

    def test_data_retrieval(self):
        """Test comprehensive data retrieval scenarios."""
        # Create multiple users with standups
        user1_id = self.create_test_user("1")
        user2_id = self.create_test_user("2")
        
        # Create standups for different dates
        dates = [
            datetime.now().date() - timedelta(days=i)
            for i in range(7)
        ]
        
        for user_id in [user1_id, user2_id]:
            for date in dates:
                standup_id = self.memory_service.create_standup(
                    user_id,
                    date.isoformat()
                )
                # Add some items
                self.memory_service.add_standup_item(
                    standup_id,
                    StandupItemType.ACCOMPLISHMENT,
                    f"Task for {date}"
                )
                if date == dates[0]:  # Today
                    self.memory_service.add_standup_item(
                        standup_id,
                        StandupItemType.BLOCKER,
                        "Active blocker",
                        resolved=False
                    )
        
        # Test recent standups retrieval
        for user_id in [user1_id, user2_id]:
            standups = self.memory_service.get_recent_standups(user_id, days=5)
            self.assertEqual(len(standups), 5)
            self.assertEqual(
                standups[0]["date"],
                dates[0].isoformat()
            )
        
        # Test blocker retrieval
        for user_id in [user1_id, user2_id]:
            blockers = self.memory_service.get_unresolved_blockers(user_id)
            self.assertEqual(len(blockers), 1)
            self.assertEqual(blockers[0]["description"], "Active blocker")

if __name__ == "__main__":
    unittest.main() 