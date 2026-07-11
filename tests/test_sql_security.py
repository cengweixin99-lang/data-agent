import unittest

from app.agent.sql_security import SQLSecurityError, validate_read_only_sql


class SQLSecurityTests(unittest.TestCase):
    def test_select_is_allowed(self):
        self.assertEqual(validate_read_only_sql("SELECT 1;"), "SELECT 1")

    def test_with_query_is_allowed(self):
        self.assertTrue(validate_read_only_sql("WITH t AS (SELECT 1) SELECT * FROM t").startswith("WITH"))

    def test_write_operations_are_rejected(self):
        for sql in ("UPDATE orders SET amount = 0", "DELETE FROM orders", "DROP TABLE orders"):
            with self.subTest(sql=sql):
                with self.assertRaises(SQLSecurityError):
                    validate_read_only_sql(sql)

    def test_multiple_statements_are_rejected(self):
        with self.assertRaises(SQLSecurityError):
            validate_read_only_sql("SELECT 1; DELETE FROM orders")

    def test_keywords_inside_string_are_allowed(self):
        self.assertEqual(validate_read_only_sql("SELECT 'UPDATE' AS operation"), "SELECT 'UPDATE' AS operation")


if __name__ == "__main__":
    unittest.main()