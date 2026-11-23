@echo off
set TRIAL_WRAPPER=both/stub.cmd
python "%~dp0..\stub_server.py" %*
