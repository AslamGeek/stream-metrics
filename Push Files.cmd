@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Push project files

echo Updating Git repository in:
echo %CD%
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo ERROR: Git is not installed or is not on PATH.
  goto finish
)

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
  echo This folder is not a Git repository. Initializing it now.
  git init -b main
  if errorlevel 1 goto failed
)

git remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo.
  echo Enter the URL of an empty GitHub/Git remote repository.
  set /p "REMOTE_URL=Remote URL: "
  if not defined REMOTE_URL (
    echo ERROR: No remote URL was provided.
    goto finish
  )
  git remote add origin "%REMOTE_URL%"
  if errorlevel 1 goto failed
)

for /f "delims=" %%N in ('git config user.name') do set "GIT_NAME=%%N"
if not defined GIT_NAME (
  set /p "GIT_NAME=Git author name: "
  if not defined GIT_NAME goto failed
  git config user.name "%GIT_NAME%"
)
for /f "delims=" %%E in ('git config user.email') do set "GIT_EMAIL=%%E"
if not defined GIT_EMAIL (
  set /p "GIT_EMAIL=Git author email: "
  if not defined GIT_EMAIL goto failed
  git config user.email "%GIT_EMAIL%"
)

git add -A
if errorlevel 1 goto failed
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Update Streamlit business intelligence app"
  if errorlevel 1 goto failed
) else (
  echo No file changes to commit; pushing existing commits.
)

git push -u origin HEAD
if errorlevel 1 goto failed
echo.
echo Push completed successfully.
goto finish

:failed
echo.
echo Push did not complete. Review the message above and retry.

:finish
echo.
echo This window will close in 5 seconds.
timeout /t 5 /nobreak >nul
endlocal
