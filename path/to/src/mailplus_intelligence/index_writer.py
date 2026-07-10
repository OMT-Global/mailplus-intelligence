# Implement per-record savepoints or an equivalent transaction boundary
import sqlite3

class IndexWriter:
    def __init__(self, db_connection):
        self.db_connection = db_connection
        self.cursor = self.db_connection.cursor()

    def write_index_records(self, records):
        try:
            self.cursor.execute("BEGIN TRANSACTION")
            for record in records:
                self.cursor.execute("INSERT INTO index_records VALUES (?, ?, ?)", (record['id'], record['data'], record['created_at']))
            self.cursor.execute("COMMIT")
            return True
        except sqlite3.Error as e:
            self.cursor.execute("ROLLBACK")
            return False