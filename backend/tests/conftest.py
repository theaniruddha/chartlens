import json
import os
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://chartlens@localhost:5433/chartlens_test"
)
# Tests must never hit a real model provider, regardless of .env.
os.environ["LLM_PROVIDER"] = "mock"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.loader import load_all_fixtures
from app.models import Base

FIXTURES = sorted((Path(__file__).parents[1] / "fixtures" / "patients").glob("*.json"))


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(os.environ["DATABASE_URL"])
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        load_all_fixtures(s)
        s.commit()
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    s = maker()
    yield s
    s.commit()
    s.close()


@pytest.fixture(scope="session")
def fixture_data() -> dict[str, dict]:
    return {
        json.loads(p.read_text())["patient"]["patient_id"]: json.loads(p.read_text())
        for p in FIXTURES
    }


@pytest.fixture()
def client(engine, session):
    from fastapi.testclient import TestClient

    from app.db.session import get_session
    from app.main import app

    def _test_session():
        yield session

    app.dependency_overrides[get_session] = _test_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
