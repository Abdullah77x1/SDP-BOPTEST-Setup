@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Verify.ps1"
set "boptest_exit=%ERRORLEVEL%"
if not "%boptest_exit%"=="0" echo Failed. Read the message above.
pause
exit /b %boptest_exit%
