from pathlib import Path
import sys
import tempfile
import os

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def _temp_engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    # Base.metadata is only populated as each model MODULE is imported.
    # Importing app.models here (before create_all) guarantees every table
    # is registered even if this is the very first fixture in the whole
    # test session to touch the database - without this, the first test
    # to run gets a partial schema and every later test (which benefits
    # from app.models already being cached by Python) does not, which is
    # exactly the kind of order-dependent flake this import prevents.
    import app.models  # noqa: F401
    from app.db import Base
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture()
def db_session(_temp_engine):
    """A fresh, isolated SQLite database per test - not the dev
    timetable.db, and not shared between tests."""
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_temp_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session, _temp_engine, monkeypatch):
    """A FastAPI TestClient wired to the isolated db_session above, via
    dependency override - no real server process, no shared state between
    tests. app.db.SessionLocal is ALSO monkeypatched to the same temp
    engine, because the timetable generation endpoint runs its solve in a
    FastAPI BackgroundTask that opens its own session directly (it can't
    reuse the request-scoped session across the background call) - without
    this, that background task would silently write to the real dev
    database instead of the test's isolated one. TestClient runs
    BackgroundTasks synchronously before returning, so generation results
    are available immediately after the `generate` call in a test.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from app import db as db_module

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_temp_engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSessionLocal)
    # app.main.lifespan also reads app.db.engine directly (schema
    # migrations, PRAGMA table_info, ...) - without patching this too, the
    # lifespan that fires on `with TestClient(app)` below silently runs its
    # seeding (subject_types, the default department, ...) against the
    # REAL dev database instead of this test's isolated one.
    monkeypatch.setattr(db_module, "engine", _temp_engine)

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
