from config import database_uri


def test_plain_postgres_urls_use_psycopg2():
    assert database_uri("postgresql://u:p@h:5432/db") == "postgresql+psycopg2://u:p@h:5432/db"
    assert database_uri("postgres://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"


def test_other_urls_are_unchanged():
    assert database_uri("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"
    assert database_uri("sqlite:///:memory:") == "sqlite:///:memory:"
