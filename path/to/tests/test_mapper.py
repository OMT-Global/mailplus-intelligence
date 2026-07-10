# Test distinguishing between idempotency key and uniqueness/constraint failures
import unittest
from unittest.mock import patch
from src.mailplus_intelligence.mapper import Mapper

class TestMapper(unittest.TestCase):
    def setUp(self):
        self.db_connection = sqlite3.connect(':memory:')
        self.mapper = Mapper(self.db_connection)

    def tearDown(self):
        self.db_connection.close()

    @patch('sqlite3.Error')
    def test_idempotency_key(self, mock_error):
        record = {'id': 1, 'data': 'data1', 'created_at': '2022-01-01'}
        existing_record = self.mapper.map_record(record)
        self.assertIsNotNone(existing_record)

    @patch('sqlite3.Error')
    def test_uniqueness_constraint(self, mock_error):
        record = {'id': 1, 'data': 'data1', 'created_at': '2022-01-01'}
        existing_record = self.mapper.map_record(record)
        self.assertIsNone(existing_record)