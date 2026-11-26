import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def database_uri(url):
    """Pin the psycopg2 driver for plain postgres URLs.

    SQLAlchemy 2.1 maps a bare "postgresql://" URL to psycopg (v3), which this
    project does not install; it uses psycopg2-binary. An explicit driver in
    the URL is kept as it is.
    """
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


class Config:
    SECRET_KEY = os.environ["SECRET_KEY"]
    SQLALCHEMY_DATABASE_URI = database_uri(os.environ["DATABASE_URL"])
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
    }

    JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(seconds=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 900)))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(seconds=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES", 604800)))
    JWT_TOKEN_LOCATION = ["headers", "cookies"]
    JWT_COOKIE_SECURE = True
    JWT_COOKIE_CSRF_PROTECT = True

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

    ORG_REGISTRATION_TOKEN = os.environ["ORG_REGISTRATION_TOKEN"]

    RATELIMIT_STORAGE_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    RATELIMIT_DEFAULT = "200 per minute"

    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "RMM System <noreply@example.com>")

    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "..", "uploads")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False
    JWT_COOKIE_SECURE = False
    JWT_COOKIE_CSRF_PROTECT = False


class ProductionConfig(Config):
    DEBUG = False


class TestConfig(DevelopmentConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}  # SQLite doesn't need pool options
    RATELIMIT_ENABLED = False
    RATELIMIT_STORAGE_URL = "memory://"
    BCRYPT_ROUNDS = 4  # bcrypt is O(2^rounds) — 4 vs 12 is ~250x faster; irrelevant for ephemeral test data


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestConfig,
    "default": DevelopmentConfig,
}
