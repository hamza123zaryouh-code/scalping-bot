"""Tests for single-instance lock in run_live_bot.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch


def _import_script():
    """Import scripts/run_live_bot.py without sys.path assumptions."""
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "run_live_bot.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_live_bot", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_acquire_lock_creates_lockfile(tmp_path):
    mod = _import_script()
    lock_file = tmp_path / "bot.lock"

    with patch.object(mod, "_LOCK_FILE", lock_file):
        with patch("atexit.register"):
            mod._acquire_single_instance_lock()

    assert lock_file.exists()
    assert lock_file.read_text().strip() == str(os.getpid())


def test_acquire_lock_raises_when_process_alive(tmp_path):
    mod = _import_script()
    lock_file = tmp_path / "bot.lock"
    # Write our own PID — definitely alive
    lock_file.write_text(str(os.getpid()))

    with patch.object(mod, "_LOCK_FILE", lock_file):
        try:
            mod._acquire_single_instance_lock()
            raise AssertionError("Expected SystemExit was not raised")
        except SystemExit as exc:
            assert str(os.getpid()) in str(exc)


def test_acquire_lock_removes_stale_lock(tmp_path):
    mod = _import_script()
    lock_file = tmp_path / "bot.lock"
    # Write a PID that is extremely unlikely to exist
    lock_file.write_text("999999999")

    with patch.object(mod, "_LOCK_FILE", lock_file):
        with patch("atexit.register"):
            mod._acquire_single_instance_lock()

    # Stale lock was overwritten with current PID
    assert lock_file.read_text().strip() == str(os.getpid())


def test_main_calls_lock_before_anything_else(tmp_path):
    """main() must call _acquire_single_instance_lock() so a second instance fails."""
    mod = _import_script()
    lock_file = tmp_path / "bot.lock"
    lock_called = []

    def fake_lock():
        lock_called.append(True)
        raise SystemExit("lock acquired — stopping test early")

    with (
        patch.object(mod, "_LOCK_FILE", lock_file),
        patch.object(mod, "_acquire_single_instance_lock", side_effect=fake_lock),
        patch.object(mod, "_parse_args", return_value=type("A", (), {"log_level": "INFO", "mode": None, "dry_run": False})()),
    ):
        try:
            mod.main()
        except SystemExit:
            pass

    assert lock_called, "_acquire_single_instance_lock() was not called from main()"
