@echo off
set TRIAL_WRAPPER=onlyenv/trialstubenv.cmd
python "%~dp0..\stub_server.py" %*
