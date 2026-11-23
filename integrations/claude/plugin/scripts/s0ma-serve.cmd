@echo off
rem s0ma-serve.cmd - start the s0ma MCP server for Claude Code on Windows.
rem
rem The plugin's .mcp.json names scripts/s0ma-serve as the server's command, and
rem on Windows Claude Code runs this file of the same name through cmd.exe. It
rem does what the POSIX script does: find uv; if uv has a Python 3.11 or newer
rem without downloading one, hand over to the launcher's `serve`; otherwise
rem start the stand-in server, s0ma-stand-in.ps1, in Windows PowerShell, so the
rem server never shows as failed on a machine with no uv.
rem
rem Nothing here installs anything, downloads anything, or opens a connection,
rem and nothing but protocol goes to stdout.
rem
rem No labels and no goto: cmd.exe reads a file with LF endings, the only
rem endings this repository commits, reliably as long as it has neither.

setlocal

set "launcher=%~dp0..\launcher\s0ma_launch.py"

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

rem Hand over only when nothing would have to be fetched first.
set "ready="
if defined uv if exist "%launcher%" "%uv%" python find --offline --no-python-downloads ">=3.11" >nul 2>&1 && set "ready=1"
if defined ready "%uv%" run --frozen --offline --no-python-downloads --quiet --script "%launcher%" serve
if defined ready exit /b %ERRORLEVEL%

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0s0ma-stand-in.ps1"
exit /b %ERRORLEVEL%
