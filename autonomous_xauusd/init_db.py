from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from .memory_layer import MemoryLayer
from .settings import load_settings


def _table_names(memory: MemoryLayer) -> list[str]:
    inspector = inspect(memory.engine)
    return sorted(inspector.get_table_names())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test de databaseverbinding en maak de autonomous XAUUSD tabellen aan."
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Test alleen de databaseverbinding zonder tabellen aan te maken.",
    )
    args = parser.parse_args()

    settings = load_settings(Path("."))
    memory = MemoryLayer(settings.database_url)

    safe_target = settings.database_url.split("@", 1)[-1] if "@" in settings.database_url else settings.database_url
    print(f"Database target: {safe_target}")

    try:
        with memory.engine.connect() as connection:
            connection.execute(text("select 1"))
    except OperationalError as exc:
        message = str(exc)
        if "getaddrinfo failed" in message or "failed to resolve host" in message:
            raise SystemExit(
                "Database host kon niet worden gevonden. Controleer of je Supabase connection string klopt "
                "en gebruik bij voorkeur de directe database-URL of een pooler-URL uit het Supabase dashboard."
            ) from exc
        raise SystemExit(f"Databaseverbinding mislukt: {exc}") from exc

    if args.check_only:
        print("Databaseverbinding OK.")
        return

    memory.initialize()
    print("Tabellen klaar:", ", ".join(_table_names(memory)))


if __name__ == "__main__":
    main()
