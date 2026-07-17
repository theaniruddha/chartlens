"""CLI: load all synthetic fixtures into the configured database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.loader import load_all_fixtures
from app.db.session import get_session

if __name__ == "__main__":
    gen = get_session()
    session = next(gen)
    ids = load_all_fixtures(session)
    try:
        next(gen)
    except StopIteration:
        pass
    print(f"Loaded {len(ids)} patients: {', '.join(ids)}")
