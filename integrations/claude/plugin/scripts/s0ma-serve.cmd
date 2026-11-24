@echo off
rem s0ma-serve.cmd - start the s0ma MCP server for Claude Code on Windows.
rem
rem The plugin's .mcp.json names scripts/s0ma-serve as the server's command, and
rem on Windows Claude Code runs this file of the same name through cmd.exe. It
rem does what the POSIX script does: find uv; if uv has a Python s0ma supports
rem (3.11 to 3.13) without downloading one, hand over to the launcher's
rem `serve`; otherwise start the stand-in server, s0ma-stand-in.ps1, in Windows
rem PowerShell, so the server never shows as failed on a machine with no uv.
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

rem Keep the Pythons uv downloads for s0ma under s0ma's home, the folder the
rem launcher's s0ma_home names: S0MA_HOME when it is set and not blank,
rem otherwise USERPROFILE\.s0ma. A UV_PYTHON_INSTALL_DIR set by the person is
rem left alone. The lines between the two markers are the same in every batch
rem file that runs uv; a test holds them to the launcher.
rem BEGIN s0ma home
set "s0ma_dir="
if defined S0MA_HOME set "s0ma_dir=%S0MA_HOME: =%"
if not defined UV_PYTHON_INSTALL_DIR if defined s0ma_dir set "UV_PYTHON_INSTALL_DIR=%S0MA_HOME%\python"
if not defined UV_PYTHON_INSTALL_DIR if defined USERPROFILE set "UV_PYTHON_INSTALL_DIR=%USERPROFILE%\.s0ma\python"
rem END s0ma home

rem Hand over only when nothing would have to be fetched first.
set "ready="
if defined uv if exist "%launcher%" "%uv%" python find --offline --no-python-downloads ">=3.11,<3.14" >nul 2>&1 && set "ready=1"
if defined ready "%uv%" run --frozen --offline --no-python-downloads --quiet --script "%launcher%" serve
if defined ready exit /b %ERRORLEVEL%

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0s0ma-stand-in.ps1"
exit /b %ERRORLEVEL%
