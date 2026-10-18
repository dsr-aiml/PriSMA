import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["DEMO_STEP_SECONDS"] = "0"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import jobs
from app.db import Base, get_db
from app.main import app


@pytest.fixture
def hosted_query(monkeypatch):
    from app import main, model_gateway, model_profiles, research_budget
    config = model_gateway.settings().model_copy(update={"allow_hosted_models": False, "allow_hosted_queries": True, "gemini_api_key": "test-only-api-key"})
    for module in (main, model_gateway, model_profiles, research_budget):
        monkeypatch.setattr(module, "settings", lambda: config)
    return config


@pytest.fixture
def context(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(jobs, "SessionLocal", factory)
    queued = []
    monkeypatch.setattr(jobs, "enqueue", queued.append)
    with TestClient(app) as client:
        yield client, factory, queued
    app.dependency_overrides.clear()
    engine.dispose()
