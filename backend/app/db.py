from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

# SQLite needs check_same_thread=False because FastAPI serves each request
# on a worker thread; every other backend (Postgres in production) ignores
# the extra kwarg entirely if we don't pass it, so branch on the URL.
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

if settings.DATABASE_URL.startswith("sqlite"):
    # SQLite ignores FK constraints unless told otherwise per-connection.
    # Without this, every delete in the app silently leaves orphaned rows
    # instead of failing loudly or cascading as the model declares.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
