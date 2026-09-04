@echo off
cd /d "C:\dev\fpl-copilot"
if not exist data\live mkdir data\live
echo [%date% %time%] tick start >> data\live\poller.log
"C:\Users\veers\.local\bin\uv.exe" run python eval/poll_availability.py --once >> data\live\poller.log 2>&1
echo [%date% %time%] tick exit code %errorlevel% >> data\live\poller.log
