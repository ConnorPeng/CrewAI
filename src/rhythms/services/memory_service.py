from typing import Dict, List, Optional
import sqlite3
from datetime import datetime, time
import json
import logging
from enum import Enum

logger = logging.getLogger(__name__)

class StandupItemType(Enum):
    ACCOMPLISHMENT = "accomplishment"
    PLAN = "plan"
    BLOCKER = "blocker"

class MemoryService:
    def __init__(self, db_path: str = "memory.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database with necessary tables."""
        conn = sqlite3.connect(self.db_path)
        
        # Enable foreign key support - must be done for EACH connection
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                github_username TEXT NOT NULL UNIQUE,
                github_token TEXT NOT NULL,
                linear_token TEXT,
                email TEXT NOT NULL UNIQUE,
                format TEXT DEFAULT 'bullets',
                timezone TEXT DEFAULT 'UTC',
                notification_time TIME DEFAULT '09:00:00',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create conversation_states table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                state_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Create standups table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS standups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date DATE NOT NULL,
                submission_time TIMESTAMP,
                submitted BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, date)
            )
        """)
        
        # Create standup_items table with type check
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS standup_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                standup_id INTEGER NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('accomplishment', 'plan', 'blocker')),
                description TEXT NOT NULL,
                resolved BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (standup_id) REFERENCES standups(id)
            )
        """)
        
        conn.commit()
        conn.close()

    def _get_connection(self):
        """Get a database connection with foreign keys enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        return conn

    def create_user(self, github_username: str, github_token: str, email: str, 
                   linear_token: Optional[str] = None, format: str = 'bullets',
                   timezone: str = 'UTC', notification_time: time = time(9, 0)) -> int:
        """Create a new user and return their ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO users (
                    github_username, github_token, linear_token, email, 
                    format, timezone, notification_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                github_username, github_token, linear_token, email,
                format, timezone, notification_time.strftime('%H:%M:%S')
            ))
            user_id = cursor.lastrowid
            conn.commit()
            return user_id
        except sqlite3.IntegrityError as e:
            logger.error(f"Error creating user: {e}")
            raise
        finally:
            conn.close()

    def get_user(self, github_username: str) -> Optional[Dict]:
        """Retrieve user information by GitHub username."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM users WHERE github_username = ?",
            (github_username,)
        )
        
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            user_data = dict(zip(columns, row))
            conn.close()
            return user_data
        
        conn.close()
        return None

    def create_standup(self, user_id: int, date: str) -> int:
        """Create a new standup entry and return its ID. If an entry already exists for the same user_id and date, it will be overwritten."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "REPLACE INTO standups (user_id, date) VALUES (?, ?)",
                (user_id, date)
            )
            standup_id = cursor.lastrowid
            conn.commit()
            return standup_id
        except sqlite3.Error as e:
            logger.error(f"Error creating standup: {e}")
            raise
        finally:
            conn.close()

    def add_standup_item(self, standup_id: int, item_type: StandupItemType, 
                        description: str, resolved: bool = False) -> int:
        """Add an item to a standup and return its ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO standup_items (standup_id, type, description, resolved)
                VALUES (?, ?, ?, ?)
            """, (standup_id, item_type.value, description, resolved))
            item_id = cursor.lastrowid
            conn.commit()
            return item_id
        finally:
            conn.close()

    def get_recent_standups(self, user_id: int, days: int = 5) -> List[Dict]:
        """Retrieve recent standups with their items."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT s.id, s.date, s.submitted, si.type, si.description, si.resolved
            FROM standups s
            LEFT JOIN standup_items si ON s.id = si.standup_id
            WHERE s.user_id = ? AND s.date >= date('now', ?)
            ORDER BY s.date DESC, si.type
        """, (user_id, f'-{days} days'))
        
        standups = {}
        for row in cursor.fetchall():
            standup_id, date, submitted, item_type, description, resolved = row
            
            if standup_id not in standups:
                standups[standup_id] = {
                    'date': date,
                    'submitted': submitted,
                    'accomplishments': [],
                    'plans': [],
                    'blockers': []
                }
            
            if item_type and description:
                item = {'description': description, 'resolved': resolved}
                if item_type == StandupItemType.ACCOMPLISHMENT.value:
                    standups[standup_id]['accomplishments'].append(item)
                elif item_type == StandupItemType.PLAN.value:
                    standups[standup_id]['plans'].append(item)
                elif item_type == StandupItemType.BLOCKER.value:
                    standups[standup_id]['blockers'].append(item)
        
        conn.close()
        return list(standups.values())

    def submit_standup(self, standup_id: int):
        """Mark a standup as submitted."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE standups 
                SET submitted = TRUE, 
                    submission_time = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (standup_id,))
            conn.commit()
        finally:
            conn.close()

    def update_user_preferences(self, user_id: int, preferences: Dict):
        """Update user preferences."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        valid_fields = {'format', 'timezone', 'notification_time'}
        updates = {k: v for k, v in preferences.items() if k in valid_fields}
        
        if not updates:
            return
        
        try:
            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            query = f"""
                UPDATE users 
                SET {set_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """
            cursor.execute(query, (*updates.values(), user_id))
            conn.commit()
        finally:
            conn.close()

    def get_unresolved_blockers(self, user_id: int) -> List[Dict]:
        """Get all unresolved blockers for a user."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT si.description, si.created_at, s.date
            FROM standup_items si
            JOIN standups s ON si.standup_id = s.id
            WHERE s.user_id = ? 
            AND si.type = ? 
            AND si.resolved = FALSE
            ORDER BY s.date DESC
        """, (user_id, StandupItemType.BLOCKER.value))
        
        blockers = []
        for row in cursor.fetchall():
            description, created_at, date = row
            blockers.append({
                'description': description,
                'created_at': created_at,
                'date': date
            })
        
        conn.close()
        return blockers 

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Retrieve user information by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,)
        )
        
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            user_data = dict(zip(columns, row))
            conn.close()
            return user_data
        
        conn.close()
        return None 

    def save_conversation_state(self, github_username: str, state: Dict) -> str:
        """Save conversation state and return session ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Get user ID
            cursor.execute(
                "SELECT id FROM users WHERE github_username = ?",
                (github_username,)
            )
            user_id = cursor.fetchone()
            if not user_id:
                raise ValueError(f"User not found: {github_username}")
            
            # Generate unique session ID
            session_id = f"{github_username}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            
            # Save state
            cursor.execute("""
                INSERT INTO conversation_states (session_id, user_id, state_data)
                VALUES (?, ?, ?)
            """, (session_id, user_id[0], json.dumps(state)))
            
            conn.commit()
            return session_id
        finally:
            conn.close()

    def get_conversation_state(self, session_id: str) -> Optional[Dict]:
        """Retrieve conversation state by session ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT state_data
                FROM conversation_states
                WHERE session_id = ?
            """, (session_id,))
            
            result = cursor.fetchone()
            if result:
                return json.loads(result[0])
            return None
        finally:
            conn.close()

    def list_user_conversations(self, github_username: str) -> List[Dict]:
        """List all saved conversations for a user."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT cs.session_id, cs.created_at
                FROM conversation_states cs
                JOIN users u ON cs.user_id = u.id
                WHERE u.github_username = ?
                ORDER BY cs.created_at DESC
            """, (github_username,))
            
            conversations = []
            for row in cursor.fetchall():
                conversations.append({
                    'session_id': row[0],
                    'created_at': row[1]
                })
            return conversations
        finally:
            conn.close() 