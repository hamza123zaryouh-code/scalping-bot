@echo off
REM Run alle unit, smoke en regression tests (snel, geen lange integratietests)
cd /d %~dp0..
python -m pytest tests/unit/ tests/smoke/ tests/regression/ --tb=short -q
pause
