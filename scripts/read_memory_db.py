#!/usr/bin/env python
import sqlite3
from datetime import datetime
import sys
import os
from tabulate import tabulate
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def connect_to_db(db_path: str = "memory.db"):
    """Connect to the database and enable foreign key support."""
    if not os.path.exists(db_path):
        logger.error(f"Database file {db_path} not found!")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def print_table_data(cursor, query: str, title: str):
    """Execute query and print results in a formatted table."""
    cursor.execute(query)
    rows = cursor.fetchall()
    if not rows:
        print(f"\nNo data found in {title}")
        return
    
    headers = [description[0] for description in cursor.description]
    
    # If this is the users table and contains tokens, mask them
    if title == "Users" and "github_token" in headers:
        masked_rows = []
        for row in rows:
            masked_row = list(row)
            for i, header in enumerate(headers):
                if header.endswith('_token') and row[i]:
                    # Show first 4 and last 4 characters of tokens
                    token = row[i]
                    masked_row[i] = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else token
            masked_rows.append(masked_row)
        rows = masked_rows
    
    print(f"\n{title}:")
    print(tabulate(rows, headers=headers, tablefmt="grid"))
    print(f"Total {title} count: {len(rows)}")

def read_database(db_path: str = "memory.db"):
    """Read and display all data from the memory database."""
    try:
        conn = connect_to_db(db_path)
        cursor = conn.cursor()
        
        # Read Users (now including tokens)
        users_query = """
            SELECT id, github_username, github_token, linear_token, email, format, timezone, 
                   notification_time, created_at, updated_at
            FROM users
        """
        print_table_data(cursor, users_query, "Users")
        
        # Read Standups
        standups_query = """
            SELECT s.id, s.user_id, u.github_username, s.date, 
                   s.submission_time, s.submitted, s.created_at
            FROM standups s
            JOIN users u ON s.user_id = u.id
            ORDER BY s.date DESC
        """
        print_table_data(cursor, standups_query, "Standups")
        
        # Read Standup Items
        items_query = """
            SELECT si.id, s.date, u.github_username, si.type, 
                   si.description, si.resolved, si.created_at
            FROM standup_items si
            JOIN standups s ON si.standup_id = s.id
            JOIN users u ON s.user_id = u.id
            ORDER BY s.date DESC, si.type
        """
        print_table_data(cursor, items_query, "Standup Items")
        
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    # Allow specifying a different database path as command line argument
    db_path = sys.argv[1] if len(sys.argv) > 1 else "memory.db"
    read_database(db_path) 