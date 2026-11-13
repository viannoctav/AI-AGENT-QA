param([string]$List, [string]$Out)
# OCR bawaan Windows (Windows.Media.Ocr). Dipanggil oleh design_to_prd\ocr.py, tidak perlu dijalankan sendiri.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) {
    $task = $asTaskGeneric.MakeGenericMethod($t).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

$langs = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
$engine = $null
if ($langs -contains 'en-US') {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('en-US'))
}
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) {
    @{ error = 'Tidak ada bahasa OCR terpasang di Windows'; languages = $langs } | ConvertTo-Json | Out-File -Encoding utf8 $Out
    exit 2
}

$results = New-Object System.Collections.ArrayList
foreach ($p in (Get-Content -Encoding UTF8 $List)) {
    if (-not $p) { continue }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $r = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    $lines = New-Object System.Collections.ArrayList
    foreach ($l in $r.Lines) {
        $x0 = 1e9; $y0 = 1e9; $x1 = 0; $y1 = 0
        foreach ($w in $l.Words) {
            $b = $w.BoundingRect
            if ($b.X -lt $x0) { $x0 = $b.X }
            if ($b.Y -lt $y0) { $y0 = $b.Y }
            if ($b.X + $b.Width -gt $x1) { $x1 = $b.X + $b.Width }
            if ($b.Y + $b.Height -gt $y1) { $y1 = $b.Y + $b.Height }
        }
        [void]$lines.Add(@{ text = $l.Text; x = [int]$x0; y = [int]$y0; w = [int]($x1 - $x0); h = [int]($y1 - $y0) })
    }
    $stream.Dispose()
    [void]$results.Add(@{ file = [string]$p; ms = $sw.ElapsedMilliseconds; lines = $lines })
}
@{ engine_language = $engine.RecognizerLanguage.LanguageTag; languages = $langs; results = $results } |
    ConvertTo-Json -Depth 6 | Out-File -Encoding utf8 $Out
