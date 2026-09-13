#!/bin/sh
set -eu
: "${POSTGRES_TEST_DATABASE_URL:?Set POSTGRES_TEST_DATABASE_URL, e.g. postgresql+psycopg://go:go@localhost:5432/go_hotel_test}"
export DATABASE_URL="$POSTGRES_TEST_DATABASE_URL"
alembic downgrade base || true
alembic upgrade head
pytest -q tests_postgres
