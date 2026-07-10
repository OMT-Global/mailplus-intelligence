# Add new fields to store rejected-record information
import sqlite3

class Schema:
    def __init__(self, db_connection):
        self.db_connection = db_connection
        self.cursor = self.db_connection.cursor()

    def create_schema(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS rejected_records (
                id INTEGER PRIMARY KEY,
                data TEXT,
                created_at TEXT
            )
        """)
        self.db_connection.commit()