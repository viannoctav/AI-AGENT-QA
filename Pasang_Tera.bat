@echo off
setlocal
cd /d "%~dp0"
title TERA - Pemasang sekali klik
rem Memasang semua yang dibutuhkan TERA: Python, Ollama, komponen, model AI, bahasa OCR, shortcut Desktop.
rem Aman dijalankan ulang: yang sudah terpasang akan dilewati.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\pasang_tera.ps1"
if errorlevel 1 (
  echo.
  echo Pemasangan belum selesai. Baca pesan di atas, perbaiki, lalu klik dua kali Pasang_Tera.bat lagi.
  echo.
  pause
)
exit /b 0
