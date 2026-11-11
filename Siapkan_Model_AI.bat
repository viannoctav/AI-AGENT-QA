@echo off
setlocal
cd /d "%~dp0"
title Tera - Unduh model AI

where ollama >nul 2>nul
if errorlevel 1 (
  echo.
  echo [!] Ollama belum terpasang. Install dari https://ollama.com/download lalu jalankan file ini lagi.
  echo.
  pause
  exit /b 1
)

rem Nama model dibaca dari configs\ai.json, jadi selalu sama dengan yang dipakai Tera
for /f "usebackq delims=" %%m in (`powershell -NoProfile -Command "$c = Get-Content 'configs\ai.json' -Raw | ConvertFrom-Json; @($c.v2.generation_model, $c.v2.judge_model, $c.v2.auto_model) | Where-Object { $_ } | Select-Object -Unique"`) do (
  echo.
  echo Mengunduh model AI: %%m
  ollama pull %%m
)

echo.
echo Selesai. Sekarang jalankan Jalankan_Tera.bat
echo.
pause
