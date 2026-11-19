@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if exist "%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe" set "PATH=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin;%PATH%"
docker info >nul 2>nul
if errorlevel 1 (
  echo Start Docker Desktop and wait for Engine running, then launch this file again.
  pause
  exit /b 1
)
if not exist ".env" (
  powershell.exe -NoProfile -Command "$r=[Security.Cryptography.RandomNumberGenerator]::Create(); $b=New-Object byte[] 48; $r.GetBytes($b); [IO.File]::WriteAllLines('.env',[string[]]@(('JWT_SECRET='+[Convert]::ToBase64String($b)),'COOKIE_SECURE=false')); $r.Dispose()"
  if errorlevel 1 goto failed
)
docker compose config --quiet
if errorlevel 1 goto failed
docker compose up --build -d
if errorlevel 1 goto failed
powershell.exe -NoProfile -Command "for($i=0;$i -lt 30;$i++){try{if((Invoke-RestMethod 'http://localhost:5173/api/health' -TimeoutSec 3).ready){exit 0}}catch{};Start-Sleep 2};exit 1"
if errorlevel 1 goto failed
start "" "http://localhost:5173/dashboard"
exit /b 0
:failed
echo RepoMind could not start. Read the error above. Check Docker Desktop, the project .env and port 5173.
echo Existing data volumes are preserved.
pause
exit /b 1
