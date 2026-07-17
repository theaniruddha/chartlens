#!/usr/bin/env bash
# One-time PostgreSQL 17 setup for ChartLens. Run with: bash scripts/setup_pg17.sh
# Creates the chartlens role + databases and enables pgvector.
set -euo pipefail

sudo -u postgres psql <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'chartlens') THEN
    CREATE ROLE chartlens LOGIN SUPERUSER PASSWORD 'chartlens';
  END IF;
END $$;
SQL

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='chartlens'" | grep -q 1 \
  || sudo -u postgres createdb -O chartlens chartlens
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='chartlens_test'" | grep -q 1 \
  || sudo -u postgres createdb -O chartlens chartlens_test

sudo -u postgres psql -d chartlens -c "CREATE EXTENSION IF NOT EXISTS vector;"
sudo -u postgres psql -d chartlens_test -c "CREATE EXTENSION IF NOT EXISTS vector;"

echo "PG17 ready. Role: chartlens / password: chartlens, databases: chartlens, chartlens_test (port 5432), pgvector enabled."
echo "Point ChartLens at it by setting in .env:"
echo "  DATABASE_URL=postgresql+psycopg://chartlens:chartlens@localhost:5432/chartlens"
echo "  TEST_DATABASE_URL=postgresql+psycopg://chartlens:chartlens@localhost:5432/chartlens_test"
