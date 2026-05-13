from __future__ import annotations

from sqlalchemy import inspect

from autonomous_xauusd.memory_layer import MemoryLayer


def test_memory_layer_initialize_creates_expected_tables(tmp_path):
    db_path = tmp_path / "autonomous.db"
    memory = MemoryLayer(f"sqlite:///{db_path.as_posix()}")

    memory.initialize()

    inspector = inspect(memory.engine)
    table_names = set(inspector.get_table_names())
    assert {"trade_logs", "model_snapshots", "runtime_state"}.issubset(table_names)
