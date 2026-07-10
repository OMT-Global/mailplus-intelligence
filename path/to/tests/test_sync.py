# Test atomic commit of record mutations and checkpoint advancement
import unittest
from unittest.mock import patch
from src.mailplus_intelligence.sync import Sync

class TestSync(unittest.TestCase):
    def setUp(self):
        self.db_connection = sqlite3.connect(':memory:')
        self.sync = Sync(self.db_connection)

    def tearDown(self):
        self.db_connection.close()

    @patch('sqlite3.Error')
    def test_atomic_commit(self, mock_error):
        records = [{'id': 1, 'data': 'data1', 'created_at': '2022-01-01'}, {'id': 2, 'data': 'data2', 'created_at': '2022-01-02'}]
        self.sync.sync_records(records)
        self.assertTrue(mock_error.called)

    @patch('sqlite3.Error')
    def test_checkpoint_advancement(self, mock_error):
        records = [{'id': 1, 'data': 'data1', 'created_at': '2022-01-01'}, {'id': 2, 'data': 'data2', 'created_at': '2022-01-02'}]
        self.sync.sync_records(records)
        self.assertTrue(mock_error.called)