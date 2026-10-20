"""Test options. --neo4j-test-db names a separate Neo4j database for the live loader tests; without it
they are skipped. It must never be the server's home database."""


def pytest_addoption(parser):
    parser.addoption("--neo4j-test-db", default=None,
                     help="a separate Neo4j database (name containing 'test') for the live loader tests")
