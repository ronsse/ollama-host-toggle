@echo off
REM Launch ollama-host-toggle windowless (no console). Used by the Startup shortcut.
cd /d "%~dp0"
start "" pythonw.exe -m ollama_host_toggle
