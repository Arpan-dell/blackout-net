@echo off
rem Compile and upload one node with the Arduino IDE's own tools, one compiler at a time
rem (the IDE's Upload button runs one compiler per CPU core and can run this laptop out of memory).
rem
rem   tools\upload_node.bat A COM14          node A on an ESP32 DevKit
rem   tools\upload_node.bat B COM8 8266      node B on a NodeMCU (ESP8266)
rem
rem The sketches come from:  python tools\make_arduino_sketch.py
if "%~2"=="" (
  echo Use: tools\upload_node.bat A COM7 [8266]    ^(node A, B or C, the board's COM port, 8266 for a NodeMCU^)
  exit /b 1
)
set "FQBN=esp32:esp32:esp32"
if "%~3"=="8266" set "FQBN=esp8266:esp8266:nodemcuv2"
set "CLI=%LOCALAPPDATA%\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
"%CLI%" --config-file "%USERPROFILE%\.arduinoIDE\arduino-cli.yaml" compile --jobs 1 --fqbn %FQBN% ^
  --upload -p %2 "%~dp0..\arduino\blackout_node_%1"
