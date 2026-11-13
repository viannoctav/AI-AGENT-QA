@echo off
setlocal
cd /d "%~dp0"
title TERA - Server AI dan Admin Akun
set "PORT=11500"
rem Menyalakan Server AI bersama dan membuka halaman admin akun (buat/nonaktifkan/hapus akun teman).
rem Bila Server AI sudah berjalan, file ini cukup membuka lagi halaman adminnya.
rem Teman memakai AI di komputer ini lewat Tailscale dan wajib login.
rem Hanya dijalankan di SATU komputer: komputer yang AI-nya dipakai bersama.

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [!] TERA belum terpasang di komputer ini. Klik dua kali Pasang_Tera.bat dulu.
  echo.
  pause
  exit /b 1
)

where tailscale >nul 2>nul
if errorlevel 1 if not exist "C:\Program Files\Tailscale\tailscale.exe" (
  echo.
  echo [!] Tailscale belum terpasang. Pasang dari https://tailscale.com/download lalu masuk.
  echo     Server tetap dinyalakan, tapi teman belum bisa terhubung sebelum Tailscale aktif.
  echo.
)

rem Izinkan koneksi masuk HANYA dari jaringan Tailscale (sekali saja, Windows akan meminta izin admin)
netsh advfirewall firewall show rule name="TERA Server AI" >nul 2>nul
if errorlevel 1 (
  echo Membuka pintu firewall khusus jaringan Tailscale. Klik Yes bila Windows meminta izin...
  powershell -NoProfile -Command "Start-Process netsh -Verb RunAs -Wait -ArgumentList 'advfirewall firewall add rule name=\"TERA Server AI\" dir=in action=allow protocol=TCP localport=%PORT% remoteip=100.64.0.0/10'" >nul 2>nul
)

".venv\Scripts\python.exe" -m ai_server --port %PORT%
pause
exit /b 0
