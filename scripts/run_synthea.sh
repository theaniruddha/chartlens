#!/usr/bin/env bash
# Generate synthetic patients with Synthea (FHIR R4) into ./synthea_output.
# Usage: bash scripts/run_synthea.sh [num_patients] [state]
# Downloads a portable JRE and the Synthea jar on first run (no root needed).
set -euo pipefail

NUM=${1:-3}
STATE=${2:-Massachusetts}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="$HOME/.local/synthea"
JRE_DIR="$HOME/.local/jre21"
OUT="$ROOT/synthea_output"

mkdir -p "$TOOLS"

# 1) Java: system java if present, else portable Temurin JRE 21
if command -v java >/dev/null 2>&1; then
  JAVA=java
elif [ -x "$JRE_DIR/bin/java" ]; then
  JAVA="$JRE_DIR/bin/java"
else
  echo "Downloading portable JRE 21 (Temurin)..."
  mkdir -p "$JRE_DIR"
  curl -sL "https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jre/hotspot/normal/eclipse" \
    | tar xz -C "$JRE_DIR" --strip-components=1
  JAVA="$JRE_DIR/bin/java"
fi

# 2) Synthea jar
JAR="$TOOLS/synthea-with-dependencies.jar"
if [ ! -f "$JAR" ]; then
  echo "Downloading Synthea (one-time, ~200 MB)..."
  curl -sL -o "$JAR" \
    "https://github.com/synthetichealth/synthea/releases/download/master-branch-latest/synthea-with-dependencies.jar"
fi

# 3) Generate
"$JAVA" -jar "$JAR" \
  -p "$NUM" \
  --exporter.fhir.export=true \
  --exporter.hospital.fhir.export=false \
  --exporter.practitioner.fhir.export=false \
  --exporter.baseDirectory="$OUT" \
  "$STATE"

echo
echo "FHIR bundles in $OUT/fhir — import with:"
echo "  cd backend && uv run python scripts/import_synthea.py"
