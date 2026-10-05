@echo off
REM ---------------------------------------------------------------
REM  This file is deliberately 100% ASCII.
REM  cmd.exe parses .bat bytes using the local codepage (GBK on a
REM  Chinese Windows). Chinese text here gets mangled, and a mangled
REM  multibyte sequence can even swallow the closing ")" of a block.
REM  So: no Chinese, no parenthesised blocks, all UI lives in Python.
REM  Chinese instructions live in the .md files next to this one.
REM ---------------------------------------------------------------
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Coupon Hunter

python run.py menu
if errorlevel 1 goto fallback
pause
exit /b 0

:fallback
py -3 run.py menu
if errorlevel 1 goto nopython
pause
exit /b 0

:nopython
echo.
echo   [X] Python not found.
echo.
echo   Install it from https://www.python.org/downloads/
echo   During install, tick the box "Add Python to PATH".
echo   Then double-click this file again.
echo.
echo   Chinese help: open the file whose name ends with .md,
echo   and read section 6 (FAQ).
echo.
pause
exit /b 1
