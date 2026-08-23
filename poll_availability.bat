@echo off
cd /d "C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
"C:\Users\veers\.local\bin\uv.exe" run python eval/poll_availability.py --once