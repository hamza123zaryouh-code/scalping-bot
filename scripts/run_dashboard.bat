@echo off
REM Start the Streamlit dashboard
call .venv\Scripts\activate.bat 2>NUL
streamlit run frontend\app.py --server.port 8501
