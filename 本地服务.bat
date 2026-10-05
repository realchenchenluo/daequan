@echo off
REM ---------------------------------------------------------------
REM  Starts the local coupon web server.
REM  100%% ASCII on purpose - see the note in the other .bat for why.
REM  Chinese help: open the .md file, section 3.
REM ---------------------------------------------------------------
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Coupon Hunter - local server

python run.py serve --open
if errorlevel 1 goto fallback
goto end

:fallback
py -3 run.py serve --open
if errorlevel 1 goto nopython
goto end

:nopython
echo.
echo   [X] Python not found.
echo   Install from https://www.python.org/downloads/ and tick "Add Python to PATH".
echo.
pause
exit /b 1

:end
echo.
echo   Server stopped.
pause
