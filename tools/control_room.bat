@echo off
rem Double-click: starts the control room and finds node C on this laptop's USB by itself.
rem Add options after it as usual, e.g.  control_room.bat --gcs http://localhost:8765
python "%~dp0control_room.py" %*
pause
