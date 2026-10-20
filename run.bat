@echo off
rem Start Rankloom. Extra arguments pass through, e.g.  run.bat --port 8140
cd /d "%~dp0"
uv run python -m rankloom.server %*
