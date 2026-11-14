@echo off
rem Double-click: starts the control room. It finds node C on this laptop's USB by itself,
rem pulls the gimbal camera straight from the Jetson (always on, GCS or not) and uses the GCS when it runs.
rem Change the addresses here if your network changes. Extra options can follow, e.g.  control_room.bat --range 800
python "%~dp0control_room.py" --camera rtsp://192.168.88.121:8554/zr10 --gcs http://localhost:8765 --scout S-01 --relays I-01=B --hq-on-scout %*
pause
