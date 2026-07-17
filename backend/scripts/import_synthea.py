"""CLI: import Synthea FHIR bundles into the configured database.

Usage: uv run python scripts/import_synthea.py [path/to/fhir_dir]
Default path: ../synthea_output/fhir (created by scripts/run_synthea.sh)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import get_session
from app.db.synthea_importer import import_directory

if __name__ == "__main__":
    fhir_dir = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else Path(__file__).resolve().parents[2] / "synthea_output" / "fhir"
    )
    if not fhir_dir.is_dir():
        sys.exit(f"No FHIR directory at {fhir_dir}. Run scripts/run_synthea.sh first.")
    gen = get_session()
    session = next(gen)
    result = import_directory(session, fhir_dir)
    try:
        next(gen)
    except StopIteration:
        pass
    print(f"Imported {len(result['patients'])} patients: {', '.join(result['patients'])}")
    for key, count in sorted(result["counts"].items()):
        print(f"  {key}: {count}")
