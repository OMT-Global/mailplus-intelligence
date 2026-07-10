# Persist rejected-record information or return a durable quarantine result
import sqlite3

class Sync:
    def __init__(self, db_connection):
        self.db_connection = db_connection
        self.cursor = self.db_connection.cursor()

    def sync_records(self, records):
        try:
            self.cursor.execute("BEGIN TRANSACTION")
            for record in records:
                if record['status'] == 'rejected':
                    self.cursor.execute("INSERT INTO rejected_records VALUES (?, ?, ?)", (record['id'], record['data'], record['created_at']))
                else:
                    self.cursor.execute("INSERT INTO index_records VALUES (?, ?, ?)", (record['id'], record['data'], record['created_at']))
            self.cursor.execute("UPDATE checkpoint SET last_synced_at = ?", (records[-1]['created_at'],))
            self.cursor.execute("COMMIT")
            return True
        except sqlite3.Error as e:
            self.cursor.execute("ROLLBACK")
            return False