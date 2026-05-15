"""Singleton circuit breaker instance — gedeeld door alle modules."""
from __future__ import annotations
from .risk_engine import CircuitBreaker

_instance: CircuitBreaker | None = None


def get_circuit_breaker() -> CircuitBreaker:
    global _instance
    if _instance is None:
        _instance = CircuitBreaker()
    return _instance
