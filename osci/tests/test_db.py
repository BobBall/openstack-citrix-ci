import unittest

from osci import db


class TestDB(unittest.TestCase):
    def test_database_initialisation(self):
        database = db.DB("sqlite://")
        database.create_schema()

        # Check that the table is created
        self.assertEquals([], database.query("SELECT * FROM test"))

    def test_execute_an_insert(self):
        database = db.DB("sqlite://")

        database.execute("CREATE TABLE A (col VARCHAR)")
        database.execute("INSERT INTO A VALUES (12)")

        self.assertEquals([("12",)], database.query("SELECT * FROM A"))

    def test_mapping_includes_constraint(self):
        database = db.DB("sqlite://")
        database.create_schema()

        database.execute(
            "INSERT INTO test (project_name, change_num) VALUES"
            "('proj', 'chang')")

        with self.assertRaises(db.IntegrityError):
            database.execute(
                "INSERT INTO test (project_name, change_num) VALUES"
                "('proj', 'chang')")
