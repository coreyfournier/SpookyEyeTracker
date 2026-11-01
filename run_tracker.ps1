# Starts the person tracker + config UI (http://localhost:8080).
# Pass --no-cameras to only run the UI and eye link (servo calibration).
Set-Location "$PSScriptRoot\tracker"
& "$PSScriptRoot\.venv\Scripts\python.exe" -m eyetracker @args
