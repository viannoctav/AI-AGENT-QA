@echo off
setlocal
cd /d "%~dp0"
title TERA - Perbarui ke versi terbaru
rem Mengunduh versi TERA terbaru dari GitHub dan memasangnya. Tutup TERA dulu sebelum menjalankan ini.
rem Hasil kerja (runs, outputs), dokumen PRD, akun, dan pengaturan TIDAK diubah.

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [!] TERA belum terpasang di komputer ini. Klik dua kali Pasang_Tera.bat dulu.
  echo.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m tools.updater
echo.
pause
exit /b 0
