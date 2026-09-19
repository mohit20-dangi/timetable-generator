from pymongo import MongoClient, ASCENDING
from pymongo.database import Database
from app.core.config import settings

_client: MongoClient = MongoClient(settings.MONGODB_URL)
_db: Database = _client[settings.MONGODB_DB_NAME]


def get_database() -> Database:
    """FastAPI dependency yielding the Mongo database handle."""
    return _db


def create_indexes() -> None:
    """Create the indexes the app relies on. Safe to call repeatedly (no-op if present).

    Every entity collection uses its own string id as Mongo's `_id`, which is
    already uniquely indexed by default, so only secondary lookup indexes are
    needed here.
    """
    _db.admins.create_index("username", unique=True)
    _db.invites.create_index("token", unique=True)
    _db.sections.create_index("year_id")
    _db.timetable_runs.create_index([("created_at", ASCENDING)])
    _db.timetable_runs.create_index("status")
