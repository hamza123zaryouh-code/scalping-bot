"""
XAUUSD V17 Config Watcher — Hot Reload Zonder Restart
======================================================
Bewaakt configuratiebestanden en herlaadt parameters on-the-fly.

Gebruik:
    watcher = ConfigWatcher("configs/live.yaml")
    watcher.start()

    # Later:
    cfg = watcher.get_config()   # Altijd up-to-date
    watcher.stop()

Callbacks:
    watcher.on_change(callback_fn)   # Wordt opgeroepen bij elke wijziging

Ondersteunde formaten: YAML, JSON
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


class ConfigWatcher:
    """
    Bewaakt een configuratiebestand en herlaadt bij wijziging.
    Thread-safe, non-blocking via background thread.
    """

    def __init__(
        self,
        config_path: str | Path,
        poll_interval: float = 5.0,
        auto_start: bool = True,
    ):
        self._path = Path(config_path)
        self._poll_interval = poll_interval
        self._config: dict = {}
        self._last_mtime: float = 0.0
        self._last_loaded: Optional[datetime] = None
        self._callbacks: list[Callable] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        # Initieel laden
        self._load()

        if auto_start:
            self.start()

    def start(self) -> None:
        """Start de background watcher thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="config-watcher",
        )
        self._thread.start()
        logger.info("ConfigWatcher gestart voor: %s", self._path)

    def stop(self) -> None:
        """Stop de background watcher thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("ConfigWatcher gestopt")

    def on_change(self, callback: Callable[[dict], None]) -> None:
        """Registreer een callback die bij configuratiewijziging wordt opgeroepen."""
        self._callbacks.append(callback)

    def get_config(self) -> dict:
        """Geeft de huidige (mogelijk versverse) configuratie terug."""
        with self._lock:
            return dict(self._config)

    def get(self, key: str, default: Any = None) -> Any:
        """Haal een specifieke configuratiewaarde op."""
        with self._lock:
            return self._config.get(key, default)

    def set_override(self, key: str, value: Any) -> None:
        """Zet een runtime override (wordt overschreven bij reload)."""
        with self._lock:
            self._config[key] = value
        logger.info("Config override: %s = %s", key, value)

    def reload(self) -> bool:
        """Forceer een reload, ongeacht wijziging. Retourneert True bij succes."""
        return self._load(force=True)

    @property
    def last_loaded(self) -> Optional[datetime]:
        return self._last_loaded

    @property
    def config_path(self) -> Path:
        return self._path

    # ─────────────────────────────────────────────────────────────
    # INTERNE METHODEN
    # ─────────────────────────────────────────────────────────────

    def _watch_loop(self) -> None:
        while self._running:
            try:
                self._check_and_reload()
            except Exception as e:
                logger.error("ConfigWatcher fout: %s", e)
            time.sleep(self._poll_interval)

    def _check_and_reload(self) -> None:
        if not self._path.exists():
            return
        mtime = self._path.stat().st_mtime
        if mtime != self._last_mtime:
            old_cfg = dict(self._config)
            changed = self._load()
            if changed:
                diff = self._diff_configs(old_cfg, self._config)
                logger.info(
                    "Config gewijzigd (%s): %d parameters bijgewerkt",
                    self._path.name, len(diff),
                )
                if diff:
                    logger.info("Gewijzigde parameters: %s", list(diff.keys()))
                for cb in self._callbacks:
                    try:
                        cb(dict(self._config))
                    except Exception as e:
                        logger.error("Config callback fout: %s", e)

    def _load(self, force: bool = False) -> bool:
        if not self._path.exists():
            logger.warning("Config bestand niet gevonden: %s", self._path)
            return False

        mtime = self._path.stat().st_mtime
        if not force and mtime == self._last_mtime:
            return False

        try:
            new_config = self._parse_file()
            with self._lock:
                self._config = new_config
                self._last_mtime = mtime
                self._last_loaded = datetime.utcnow()
            return True
        except Exception as e:
            logger.error("Config laden mislukt (%s): %s", self._path, e)
            return False

    def _parse_file(self) -> dict:
        suffix = self._path.suffix.lower()
        text = self._path.read_text(encoding="utf-8")

        if suffix in (".yaml", ".yml"):
            if not _YAML_AVAILABLE:
                raise ImportError("PyYAML niet geïnstalleerd — pip install pyyaml")
            return yaml.safe_load(text) or {}
        elif suffix == ".json":
            return json.loads(text)
        else:
            raise ValueError(f"Onbekend config formaat: {suffix}")

    @staticmethod
    def _diff_configs(old: dict, new: dict) -> dict:
        diff = {}
        all_keys = set(old) | set(new)
        for k in all_keys:
            if old.get(k) != new.get(k):
                diff[k] = {"old": old.get(k), "new": new.get(k)}
        return diff


class MultiConfigWatcher:
    """
    Bewaakt meerdere config bestanden tegelijk.
    Merged configs in volgorde (latere overschrijven eerdere).
    """

    def __init__(self, paths: list[str | Path], poll_interval: float = 5.0):
        self._watchers = [
            ConfigWatcher(p, poll_interval=poll_interval, auto_start=False)
            for p in paths
        ]
        self._merged: dict = {}
        self._callbacks: list[Callable] = []
        self._lock = threading.RLock()

        self._merge()

        for w in self._watchers:
            w.on_change(lambda cfg: self._on_child_change(cfg))
            w.start()

    def get_config(self) -> dict:
        with self._lock:
            return dict(self._merged)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._merged.get(key, default)

    def on_change(self, callback: Callable[[dict], None]) -> None:
        self._callbacks.append(callback)

    def stop(self) -> None:
        for w in self._watchers:
            w.stop()

    def _merge(self) -> None:
        merged = {}
        for w in self._watchers:
            merged.update(w.get_config())
        with self._lock:
            self._merged = merged

    def _on_child_change(self, _: dict) -> None:
        self._merge()
        for cb in self._callbacks:
            try:
                cb(dict(self._merged))
            except Exception as e:
                logger.error("MultiConfig callback fout: %s", e)


# ─────────────────────────────────────────────────────────────────
# RUNTIME STRATEGY CONFIG
# ─────────────────────────────────────────────────────────────────

class StrategyConfigManager:
    """
    Beheert de live strategy configuratie met hot reload.
    Koppelt ConfigWatcher aan de StrategyEngine parameters.

    Gebruik:
        manager = StrategyConfigManager()
        manager.start()
        cfg = manager.get_strategy_cfg()   # Altijd actueel
    """

    DEFAULT_STRATEGY_CFG = {
        "risk_a": 0.0040,
        "risk_b": 0.0030,
        "risk_c": 0.0025,
        "adx_min": 14,
        "h4adx_min": 14,
        "vol_mult": 1.00,
        "tp1_r": 1.5,
        "tp2_r": 2.5,
        "tp3_r": 4.0,
        "tp1_pct": 0.30,
        "tp2_pct": 0.30,
        "sl_atr": 1.5,
        "sl_max": 2.0,
        "max_dag": 6,
        "sl_dag_max": 2,
        "cooldown_h": 2,
        "trailing": True,
        "max_spread": 350,
        "sentiment_enabled": True,
        "circuit_breaker_enabled": True,
    }

    def __init__(self, config_path: str = "configs/live_strategy.json"):
        self._path = Path(config_path)
        self._cfg = dict(self.DEFAULT_STRATEGY_CFG)
        self._watcher: Optional[ConfigWatcher] = None
        self._lock = threading.RLock()
        self._reload_count = 0
        self._last_reload: Optional[datetime] = None

        self._ensure_config_exists()
        self._watcher = ConfigWatcher(self._path, auto_start=False)
        self._watcher.on_change(self._on_config_change)

    def start(self) -> None:
        if self._watcher:
            self._watcher.start()
            self._on_config_change(self._watcher.get_config())

    def stop(self) -> None:
        if self._watcher:
            self._watcher.stop()

    def get_strategy_cfg(self) -> dict:
        with self._lock:
            return dict(self._cfg)

    def update_parameter(self, key: str, value: Any) -> bool:
        """Live parameter update zonder bestand te wijzigen."""
        if key not in self.DEFAULT_STRATEGY_CFG:
            logger.warning("Onbekende parameter: %s", key)
            return False
        with self._lock:
            self._cfg[key] = value
        logger.info("Live parameter update: %s = %s", key, value)
        return True

    def get_status(self) -> dict:
        return {
            "config_path": str(self._path),
            "reload_count": self._reload_count,
            "last_reload": self._last_reload.isoformat() if self._last_reload else None,
            "current_config": self.get_strategy_cfg(),
        }

    def _on_config_change(self, new_cfg: dict) -> None:
        with self._lock:
            for key, default in self.DEFAULT_STRATEGY_CFG.items():
                if key in new_cfg:
                    val = new_cfg[key]
                    expected_type = type(default)
                    try:
                        self._cfg[key] = expected_type(val)
                    except (TypeError, ValueError):
                        self._cfg[key] = default
            self._reload_count += 1
            self._last_reload = datetime.utcnow()
        logger.info("Strategy config bijgewerkt (reload #%d)", self._reload_count)

    def _ensure_config_exists(self) -> None:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self.DEFAULT_STRATEGY_CFG, f, indent=2)
            logger.info("Default strategy config aangemaakt: %s", self._path)
