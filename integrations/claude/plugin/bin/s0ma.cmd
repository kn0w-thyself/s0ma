@echo off
rem s0ma.cmd - run the s0ma command that belongs to this project.
rem
rem The twin of bin/s0ma for a Windows shell with no Git Bash. Claude Code adds
rem this plugin's bin/ directory to the PATH of the commands it runs, and
rem Windows finds this file for `s0ma` through PATHEXT. It does what the POSIX
rem script does: find uv, then hand everything to the launcher beside it.
rem
rem No labels and no goto: cmd.exe reads a file with LF endings, the only
rem endings this repository commits, reliably as long as it has neither.

setlocal

set "launcher=%~dp0..\launcher\s0ma_launch.py"
if not exist "%launcher%" echo s0ma is missing a file it needs, %launcher% - installing the s0ma plugin again should put it back. 1>&2
if not exist "%launcher%" exit /b 1

rem Find uv the way the launcher does: whatever the PATH offers first, then the
rem places uv's own installers put it on Windows. The list between the two
rem markers is the launcher's uv_candidates for Windows; a test fails if the two
rem drift apart.
set "uv="
for %%I in (uv.exe) do set "uv=%%~$PATH:I"
rem BEGIN uv places
if not defined uv if defined USERPROFILE if exist "%USERPROFILE%\.local\bin\uv.exe" set "uv=%USERPROFILE%\.local\bin\uv.exe"
if not defined uv if defined LOCALAPPDATA if exist "%LOCALAPPDATA%\uv\bin\uv.exe" set "uv=%LOCALAPPDATA%\uv\bin\uv.exe"
if not defined uv if defined USERPROFILE if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "uv=%USERPROFILE%\.cargo\bin\uv.exe"
if not defined uv if defined ProgramFiles if exist "%ProgramFiles%\uv\uv.exe" set "uv=%ProgramFiles%\uv\uv.exe"
rem END uv places

if not defined uv echo s0ma needs a small program called uv, and it is not on this computer yet - install it with: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" 1>&2
if not defined uv exit /b 7

"%uv%" run --frozen --script "%launcher%" run -- s0ma %*
exit /b %ERRORLEVEL%
