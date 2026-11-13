@echo off
setlocal
cd /d "%~dp0"
title Tera - Asisten QA berbasis AI

rem Cari Python: utamakan "py" launcher, lalu "python"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)

rem Pertama kali: buat folder .venv dan pasang komponen dari requirements.txt
if not exist ".venv\Scripts\python.exe" (
  if not defined PY (
    echo.
    echo [!] Python belum terpasang.
    echo     Klik dua kali Pasang_Tera.bat untuk memasang semuanya otomatis.
    echo.
    pause
    exit /b 1
  )
  echo.
  echo Menyiapkan Tera untuk pertama kali. Butuh internet dan beberapa menit...
  echo.
  %PY% -m venv .venv
  if errorlevel 1 goto gagal
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto gagal
  echo.
  echo Persiapan selesai.
)

rem Komponen yang ditambahkan di versi baru (pengolah gambar untuk Desain Konversi ke PRD)
".venv\Scripts\python.exe" -c "import PIL" >nul 2>nul
if errorlevel 1 (
  echo Memasang komponen baru: pengolah gambar. Butuh internet sebentar...
  ".venv\Scripts\python.exe" -m pip install pillow
)

where ollama >nul 2>nul
if errorlevel 1 (
  echo.
  echo [!] Ollama belum terpasang. Klik dua kali Pasang_Tera.bat untuk memasangnya otomatis.
  echo     Tera tetap dibuka, tapi AI belum bisa dipakai sampai Ollama terpasang.
  echo.
)

echo.
echo Membuka Tera di browser. JANGAN tutup jendela ini selama Tera dipakai.
echo Untuk mematikan Tera: tekan Ctrl+C atau tutup jendela ini.
echo.
".venv\Scripts\python.exe" dashboard.py
pause
exit /b 0

:gagal
echo.
echo [!] Persiapan gagal. Cek koneksi internet, hapus folder .venv, lalu jalankan file ini lagi.
echo.
pause
exit /b 1
