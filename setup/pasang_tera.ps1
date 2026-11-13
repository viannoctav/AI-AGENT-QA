# Pemasang TERA sekali klik (dipanggil oleh Pasang_Tera.bat).
# Memasang yang belum ada saja: Python, Ollama, komponen Python (.venv), model AI, bahasa OCR, shortcut Desktop.
# Aman dijalankan ulang: langkah yang sudah beres akan dilewati.
# File ini sengaja hanya memakai huruf ASCII supaya terbaca benar oleh PowerShell bawaan Windows.

$ErrorActionPreference = 'Continue'  # perintah luar (pip, ollama) menulis progres ke stderr; error dicek manual
$ProgressPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Log = Join-Path $Root 'pasang_tera.log'
try { Start-Transcript -Path $Log -Force | Out-Null } catch {}

$PY_FALLBACK_URL = 'https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe'
$OLLAMA_URL = 'https://ollama.com/download/OllamaSetup.exe'
$OLLAMA_API = 'http://127.0.0.1:11434/api/version'

function Step($n, $total, $text) { Write-Host ''; Write-Host "[$n/$total] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    OK  $text" -ForegroundColor Green }
function Info($text) { Write-Host "    $text" }
function Warn($text) { Write-Host "    !   $text" -ForegroundColor Yellow }
function Fail($text) {
    Write-Host ''
    Write-Host "[GAGAL] $text" -ForegroundColor Red
    Write-Host "Catatan lengkap ada di: $Log"
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}
function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $u = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$m;$u"
}
function Has-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }
function Download($url, $out) {
    Info "Mengunduh $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -ErrorAction Stop
}

# ---------------------------------------------------------------- Python
function Python-Version($exe, $pre) {
    try {
        $v = & $exe @pre -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -match '^(\d+)\.(\d+)$') { return [version]$v }
    } catch {}
    return $null
}
function Find-Python {
    $cands = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $cands += , @('py', @('-3')) }
    if (Get-Command python -ErrorAction SilentlyContinue) { $cands += , @('python', @()) }
    $local = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    foreach ($f in $local) { $cands += , @($f.FullName, @()) }
    foreach ($c in $cands) {
        $v = Python-Version $c[0] $c[1]
        if ($v -and $v -ge [version]'3.10') { return @{ exe = $c[0]; pre = $c[1]; ver = $v } }
    }
    return $null
}

# ---------------------------------------------------------------- Ollama
function Find-Ollama {
    $c = Get-Command ollama -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (Test-Path $p) { return $p }
    return $null
}
function Find-Tailscale {
    $c = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = "$env:ProgramFiles\Tailscale\tailscale.exe"
    if (Test-Path $p) { return $p }
    return $null
}
function Ollama-Up {
    try { Invoke-RestMethod -Uri $OLLAMA_API -TimeoutSec 3 -ErrorAction Stop | Out-Null; return $true } catch { return $false }
}

$TOTAL = 8
Write-Host '=============================================================='
Write-Host '  Pemasang TERA - Asisten QA berbasis AI'
Write-Host '  Butuh internet. Model AI sekitar 15 GB, jadi bisa cukup lama.'
Write-Host '  Jangan tutup jendela ini sampai tertulis SELESAI.'
Write-Host '=============================================================='
Write-Host ''
Write-Host 'AI yang akan dipakai di laptop ini:'
Write-Host '  1  AI di laptop ini sendiri (memasang Ollama dan model AI, unduhan sekitar 15 GB)'
Write-Host '  2  Server AI bersama milik teman (tanpa unduh model AI, butuh akun dan Tailscale)'
$Shared = $null
while ($null -eq $Shared) {
    $ans = (Read-Host 'Ketik 1 atau 2 lalu tekan Enter (kosong = 1)').Trim()
    if ($ans -eq '' -or $ans -eq '1') { $Shared = $false }
    elseif ($ans -eq '2') { $Shared = $true }
    else { Write-Host '    Pilihan hanya 1 atau 2.' -ForegroundColor Yellow }
}

# 1. Cek laptop -------------------------------------------------------------
Step 1 $TOTAL 'Memeriksa laptop'
if (-not [Environment]::Is64BitOperatingSystem) { Fail 'TERA butuh Windows 64-bit.' }
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
if ($ramGB -lt 12) { Warn "RAM laptop $ramGB GB. Disarankan 16 GB; dengan RAM lebih kecil AI akan sangat lambat atau gagal." }
else { Ok "RAM $ramGB GB" }
$sysDrive = (Get-Item $env:USERPROFILE).PSDrive.Name
$freeGB = [math]::Round((Get-PSDrive $sysDrive).Free / 1GB, 1)
$needGB = if ($Shared) { 3 } else { 20 }
if ($freeGB -lt $needGB) { Fail "Ruang kosong di drive $($sysDrive): hanya $freeGB GB. Butuh minimal $needGB GB. Kosongkan dulu lalu jalankan lagi." }
Ok "Ruang kosong drive $($sysDrive): $freeGB GB"
try { Invoke-WebRequest -Uri 'https://ollama.com' -Method Head -TimeoutSec 15 -UseBasicParsing -ErrorAction Stop | Out-Null; Ok 'Internet tersambung' }
catch { Fail 'Tidak bisa tersambung ke internet (ollama.com). Cek koneksi lalu jalankan lagi.' }

# 2. Python -----------------------------------------------------------------
Step 2 $TOTAL 'Python'
$py = Find-Python
if ($py) { Ok "Sudah terpasang (Python $($py.ver))" }
else {
    Info 'Belum ada. Memasang Python...'
    $done = $false
    if (Has-Winget) {
        try {
            winget install -e --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
            $done = $true
        } catch { Warn 'winget gagal, mencoba unduh langsung dari python.org' }
    }
    Refresh-Path
    $py = Find-Python
    if (-not $py) {
        $tmp = Join-Path $env:TEMP 'python-setup.exe'
        try { Download $PY_FALLBACK_URL $tmp } catch { Fail 'Gagal mengunduh Python. Cek internet lalu jalankan lagi.' }
        $p = Start-Process -ErrorAction Stop -FilePath $tmp -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1' -Wait -PassThru
        if ($p.ExitCode -ne 0) { Fail "Pemasangan Python gagal (kode $($p.ExitCode))." }
        Refresh-Path
        $py = Find-Python
    }
    if (-not $py) { Fail 'Python sudah dipasang tapi belum terbaca. Tutup jendela ini lalu jalankan Pasang_Tera.bat sekali lagi.' }
    Ok "Python $($py.ver) terpasang"
}

# 3. Ollama (AI di laptop ini) atau Tailscale (Server AI bersama) -----------
if ($Shared) {
    Step 3 $TOTAL 'Tailscale (jalur aman ke Server AI bersama)'
    if (Find-Tailscale) { Ok 'Sudah terpasang' }
    else {
        Info 'Belum ada. Memasang Tailscale...'
        if (Has-Winget) {
            try { winget install -e --id tailscale.tailscale --silent --accept-package-agreements --accept-source-agreements } catch { Warn 'winget gagal, mencoba unduh langsung' }
        }
        Refresh-Path
        if (-not (Find-Tailscale)) {
            $tmp = Join-Path $env:TEMP 'tailscale-setup.exe'
            try { Download 'https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe' $tmp } catch { Fail 'Gagal mengunduh Tailscale. Cek internet lalu jalankan lagi.' }
            $p = Start-Process -ErrorAction Stop -FilePath $tmp -ArgumentList '/quiet' -Wait -PassThru
            if ($p.ExitCode -ne 0) { Warn "Pemasang Tailscale selesai dengan kode $($p.ExitCode)." }
        }
        if (Find-Tailscale) { Ok 'Tailscale terpasang' } else { Warn 'Tailscale belum terbaca. Pasang manual dari https://tailscale.com/download' }
    }
    Info 'Buka Tailscale dari Start Menu, masuk, lalu terima undangan dari pemilik Server AI.'
} else { Step 3 $TOTAL 'Ollama (mesin AI lokal)' }
$ollama = if ($Shared) { $null } else { Find-Ollama }
if ($Shared) { }
elseif ($ollama) { Ok 'Sudah terpasang' }
else {
    Info 'Belum ada. Memasang Ollama...'
    if (Has-Winget) {
        try { winget install -e --id Ollama.Ollama --silent --accept-package-agreements --accept-source-agreements } catch { Warn 'winget gagal, mencoba unduh langsung dari ollama.com' }
    }
    Refresh-Path
    $ollama = Find-Ollama
    if (-not $ollama) {
        $tmp = Join-Path $env:TEMP 'OllamaSetup.exe'
        try { Download $OLLAMA_URL $tmp } catch { Fail 'Gagal mengunduh Ollama. Cek internet lalu jalankan lagi.' }
        $p = Start-Process -ErrorAction Stop -FilePath $tmp -ArgumentList '/VERYSILENT /NORESTART /SUPPRESSMSGBOXES' -Wait -PassThru
        if ($p.ExitCode -ne 0) { Fail "Pemasangan Ollama gagal (kode $($p.ExitCode))." }
        Refresh-Path
        $ollama = Find-Ollama
    }
    if (-not $ollama) { Fail 'Ollama sudah dipasang tapi belum terbaca. Tutup jendela ini lalu jalankan Pasang_Tera.bat sekali lagi.' }
    Ok 'Ollama terpasang'
}

# 4. Nyalakan Ollama --------------------------------------------------------
Step 4 $TOTAL 'Menyalakan Ollama'
if ($Shared) { Ok 'Dilewati: AI berjalan di Server AI bersama' }
elseif (-not (Ollama-Up)) {
    $app = "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
    if (Test-Path $app) { Start-Process -FilePath $app | Out-Null } else { Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden | Out-Null }
    for ($i = 0; $i -lt 60 -and -not (Ollama-Up); $i++) { Start-Sleep -Seconds 1 }
}
if ($Shared) { }
elseif (Ollama-Up) { Ok 'Ollama menyala' } else { Fail 'Ollama tidak mau menyala. Buka aplikasi Ollama dari Start Menu, lalu jalankan Pasang_Tera.bat lagi.' }

# 5. Komponen Python (.venv) ------------------------------------------------
Step 5 $TOTAL 'Komponen TERA (folder .venv)'
$venvPy = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Info 'Membuat folder .venv...'
    & $py.exe @($py.pre) -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) { Fail 'Gagal membuat folder .venv.' }
}
Info 'Memasang/memperbarui komponen dari requirements.txt (beberapa menit pertama kali)...'
& $venvPy -m pip install --upgrade pip --disable-pip-version-check -q
& $venvPy -m pip install -r requirements.txt --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail 'Gagal memasang komponen. Cek internet, hapus folder .venv, lalu jalankan lagi.' }
Ok 'Komponen siap'

# 6. Model AI ---------------------------------------------------------------
Step 6 $TOTAL 'Model AI dan model kemiripan makna (diambil dari configs\ai.json)'
if ($Shared) {
    Ok 'Dilewati: model AI ada di Server AI bersama'
    $src = Join-Path $Root 'configs\sumber_ai.json'
    if (-not (Test-Path $src)) { Set-Content -Path $src -Value '{"mode": "server"}' -Encoding ASCII }
    $models = @()
} else {
$cfg = Get-Content (Join-Path $Root 'configs\ai.json') -Raw | ConvertFrom-Json
$models = @($cfg.v2.generation_model, $cfg.v2.judge_model, $cfg.v2.auto_model, $cfg.ollama.generation_model, $cfg.ollama.judge_model, $cfg.ollama.embedding_model) |
    Where-Object { $_ } | Select-Object -Unique
$installed = (& $ollama list 2>$null | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] })
foreach ($m in $models) {
    $have = $installed | Where-Object { $_ -eq $m -or $_ -eq "$($m):latest" }
    if ($have) { Ok "$m sudah ada"; continue }
    Info "Mengunduh $m (bisa lama, tergantung internet)..."
    & $ollama pull $m
    if ($LASTEXITCODE -ne 0) { Fail "Gagal mengunduh model $m. Jalankan Pasang_Tera.bat lagi; unduhan akan dilanjutkan." }
    Ok "$m terpasang"
}
}

# 7. Bahasa OCR (untuk Desain Konversi ke PRD) ------------------------------
Step 7 $TOTAL 'Pembaca teks Windows (OCR) untuk fitur Desain Konversi ke PRD'
$ocrOk = $false
try {
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    $langs = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
    $ocrOk = [bool]($langs | Where-Object { $_ -like 'en*' })
} catch {}
if ($ocrOk) { Ok 'Bahasa Inggris untuk OCR tersedia' }
else {
    Warn 'Bahasa Inggris untuk OCR belum ada. Windows akan meminta izin admin untuk memasangnya.'
    try {
        $p = Start-Process powershell -ErrorAction Stop -Verb RunAs -Wait -PassThru -ArgumentList '-NoProfile -Command "Add-WindowsCapability -Online -Name Language.OCR~~~en-US~0.0.1.0"'
        if ($p.ExitCode -eq 0) { Ok 'Bahasa OCR dipasang' } else { throw 'gagal' }
    } catch {
        Warn 'Belum terpasang. Pasang manual: Settings > Time & language > Language & region > Add a language > English (United States).'
        Warn 'Fitur lain tetap bisa dipakai; hanya Desain Konversi ke PRD yang butuh ini.'
    }
}

# 8. Shortcut Desktop -------------------------------------------------------
Step 8 $TOTAL 'Shortcut TERA di Desktop'
try {
    $ico = Join-Path $Root 'dashboard\tera.ico'
    $desk = [Environment]::GetFolderPath('Desktop')
    $ws = New-Object -ComObject WScript.Shell -ErrorAction Stop
    $sc = $ws.CreateShortcut((Join-Path $desk 'TERA.lnk'))
    $sc.TargetPath = Join-Path $Root 'Jalankan_Tera.bat'
    $sc.WorkingDirectory = $Root
    $sc.Description = 'TERA - Asisten QA berbasis AI'
    if (Test-Path $ico) { $sc.IconLocation = $ico }
    $sc.Save()
    Ok 'Shortcut "TERA" dibuat di Desktop'
} catch { Warn 'Shortcut tidak bisa dibuat. TERA tetap bisa dibuka lewat Jalankan_Tera.bat.' }

Write-Host ''
Write-Host '=============================================================='
Write-Host '  SELESAI. TERA siap dipakai.' -ForegroundColor Green
if ($Shared) {
    Write-Host '  Saat TERA terbuka: menu Pengaturan > Sumber AI > Server AI bersama,'
    Write-Host '  isi alamat server, nama pengguna, dan password dari pemilik server.'
}
Write-Host '  Berikutnya cukup klik dua kali "TERA" di Desktop'
Write-Host '  (atau Jalankan_Tera.bat di folder ini).'
Write-Host '=============================================================='
try { Stop-Transcript | Out-Null } catch {}
$ans = Read-Host 'Buka TERA sekarang? (Y/n)'
if ($ans -notmatch '^[nN]') { Start-Process -FilePath (Join-Path $Root 'Jalankan_Tera.bat') -WorkingDirectory $Root }
exit 0
