"""Health check script — verifies all platform components are reachable."""
from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    latency_ms: float = 0.0


@dataclass
class HealthReport:
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def overall_ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "overall": "healthy" if self.overall_ok else "degraded",
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail, "latency_ms": round(c.latency_ms, 1)}
                for c in self.checks
            ],
        }


def _timed(fn: Callable) -> tuple[bool, str, float]:
    t0 = time.perf_counter()
    try:
        ok, detail = fn()
    except Exception as exc:
        ok, detail = False, str(exc)
    latency = (time.perf_counter() - t0) * 1000
    return ok, detail, latency


def check_api(base_url: str = "http://localhost:8000") -> CheckResult:
    def _check():
        r = requests.get(f"{base_url}/api/v1/health", timeout=5)
        r.raise_for_status()
        return True, r.json().get("status", "unknown")
    ok, detail, ms = _timed(_check)
    return CheckResult("api", ok, detail, ms)


def check_bot_state() -> CheckResult:
    state_path = ROOT / "live_logs" / "bot_state.json"
    if not state_path.exists():
        return CheckResult("bot_state", False, "state file not found")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        last_day = state.get("current_trading_day", "unknown")
        return CheckResult("bot_state", True, f"last_day={last_day}")
    except Exception as exc:
        return CheckResult("bot_state", False, str(exc))


def check_log_freshness(max_age_minutes: int = 30) -> CheckResult:
    log_path = ROOT / "live_logs" / "xauusd_live_bot.log"
    if not log_path.exists():
        return CheckResult("log_freshness", False, "log file missing")
    age_minutes = (time.time() - log_path.stat().st_mtime) / 60
    ok = age_minutes <= max_age_minutes
    return CheckResult("log_freshness", ok, f"age={age_minutes:.1f}min (max={max_age_minutes}min)")


def check_disk_space(min_free_gb: float = 1.0) -> CheckResult:
    import shutil
    stat = shutil.disk_usage(ROOT)
    free_gb = stat.free / (1024 ** 3)
    ok = free_gb >= min_free_gb
    return CheckResult("disk_space", ok, f"free={free_gb:.1f}GB (min={min_free_gb}GB)")


def run_health_check(api_url: str = "http://localhost:8000", log_max_age_minutes: int = 30) -> HealthReport:
    report = HealthReport()
    report.checks = [
        check_api(api_url),
        check_bot_state(),
        check_log_freshness(max_age_minutes=log_max_age_minutes),
        check_disk_space(),
    ]
    return report


def main() -> None:
    report = run_health_check()
    print(json.dumps(report.to_dict(), indent=2))
    sys.exit(0 if report.overall_ok else 1)


if __name__ == "__main__":
    main()
