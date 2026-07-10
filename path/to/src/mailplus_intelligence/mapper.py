# Distinguish between idempotency key and uniqueness/constraint failures
import sqlite3

class Mapper:
    def __init__(self, db_connection):
        self.db_connection = db_connection
        self.cursor = self.db_connection.cursor()

    def map_record(self, record):
        try:
            self.cursor.execute("SELECT * FROM index_records WHERE id = ?", (record['id'],))
            existing_record = self.cursor.fetchone()
            if existing_record:
                return existing_record
            else:
                self.cursor.execute("INSERT INTO index_records VALUES (?, ?, ?)", (record['id'], record['data'], record['created_at']))
                return self.cursor.lastrowid
        except sqlite3.Error as e:
            return None