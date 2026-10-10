@echo off
rem Double-click to start QualFrame. The first start downloads Python and the
rem required packages (a few minutes); later starts take a few seconds.
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo Installing uv, a small tool that sets up Python for QualFrame...
  powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
uv run --python 3.12 --extra llm qualframe start %*
if errorlevel 1 (
  echo.
  echo QualFrame stopped with an error. The message above says what went wrong.
  pause
)
