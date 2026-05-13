@echo off
REM Run the full test suite
call .venv\Scripts\activate.bat 2>NUL
pytest tests\ -v --cov=backend --cov=. --cov-report=term-missing
