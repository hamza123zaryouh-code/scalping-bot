"""Apply the Supabase SQL schema to the configured Postgres database."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "webapp" / "supabase" / "schema.sql"
DATABASE_ENV_ORDER = ("SUPABASE_DB_URL", "POSTGRES_URL", "SUPABASE_POOLER_URL")


def _load_environment() -> None:
    load_dotenv(ROOT / ".env")


def _resolve_database_url() -> tuple[str, str]:
    for env_name in DATABASE_ENV_ORDER:
        value = os.getenv(env_name, "").strip()
        if value:
            return env_name, _normalize_database_url(value)
    raise RuntimeError(
        "Missing database connection string. Set one of: "
        + ", ".join(DATABASE_ENV_ORDER)
    )


def _normalize_database_url(database_url: str) -> str:
    if "://" not in database_url:
        return database_url

    parsed = make_url(database_url)
    drivername = parsed.drivername

    if drivername.startswith("postgresql+"):
        parsed = parsed.set(drivername="postgresql")

    return parsed.render_as_string(hide_password=False)


def main() -> int:
    _load_environment()

    if not SCHEMA_PATH.exists():
        print(f"Schema file not found: {SCHEMA_PATH}", file=sys.stderr)
        return 1

    try:
        env_name, database_url = _resolve_database_url()
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

        with psycopg.connect(database_url, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(schema_sql)

        print(f"Applied Supabase schema from {SCHEMA_PATH} using {env_name}.")
        return 0
    except Exception as exc:  # pragma: no cover - operational script
        print(f"Failed to apply Supabase schema: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
