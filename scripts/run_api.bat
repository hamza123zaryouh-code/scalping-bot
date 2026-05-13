@echo off
REM Start the FastAPI backend
call .venv\Scripts\activate.bat 2>NUL
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
