# Windows built-in OCR (Windows.Media.Ocr) through WinRT.
#
# ASCII-only on purpose: Windows PowerShell 5.1 decodes .ps1 with the OEM code page,
# and it does not allow comments inside param().
#
# One-shot:
#   powershell -ExecutionPolicy Bypass -File ocr_helper.ps1 -Image shot.png -Out text.txt
#   powershell -ExecutionPolicy Bypass -File ocr_helper.ps1 -ListLanguages
#
# Warm process (PowerShell cold start is 3s+, so the app keeps one alive):
#   powershell -ExecutionPolicy Bypass -File ocr_helper.ps1 -Serve
#   then write "<image path>|<out path>" lines to stdin; answers are
#   "ready <lang>", "ok <lines> <ms>" or "err <message>".
#
# Recognized text is always written to -Out as UTF-8, so the caller never has to
# guess the console code page.
param(
    [string]$Image,
    [string]$Out,
    [string]$Language = "",
    [switch]$ListLanguages,
    [switch]$Serve
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime

[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

function New-OcrEngine([string]$tag) {
    if ($tag) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language $tag))
        if ($engine) { return $engine }
    }
    return [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}

function Invoke-Ocr($engine, [string]$imagePath, [string]$outPath) {
    $full = (Resolve-Path -LiteralPath $imagePath).Path
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($item in $result.Lines) { $lines.Add($item.Text) }
    [System.IO.File]::WriteAllText($outPath, [string]::Join("`n", $lines), (New-Object System.Text.UTF8Encoding $false))
    return $lines.Count
}

if ($ListLanguages) {
    foreach ($lang in [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages) { Write-Output $lang.LanguageTag }
    exit 0
}

if ($Serve) {
    $engine = New-OcrEngine $Language
    if (-not $engine) {
        [Console]::Out.WriteLine("err no OCR engine available")
        [Console]::Out.Flush()
        exit 1
    }
    [Console]::Out.WriteLine("ready " + $engine.RecognizerLanguage.LanguageTag)
    [Console]::Out.Flush()
    while ($true) {
        $line = [Console]::In.ReadLine()
        if ($null -eq $line) { break }
        $line = $line.Trim()
        if ($line -eq "quit") { break }
        if (-not $line) { continue }
        $parts = $line -split '\|', 2
        try {
            $watch = [System.Diagnostics.Stopwatch]::StartNew()
            $count = Invoke-Ocr $engine $parts[0] $parts[1]
            $watch.Stop()
            [Console]::Out.WriteLine(("ok {0} {1}" -f $count, $watch.ElapsedMilliseconds))
        } catch {
            [Console]::Out.WriteLine("err " + $_.Exception.Message)
        }
        [Console]::Out.Flush()
    }
    exit 0
}

if (-not $Image) { throw "need -Image" }
if (-not $Out) { $Out = [System.IO.Path]::ChangeExtension($Image, ".ocr.txt") }

$engine = New-OcrEngine $Language
if (-not $engine) { throw "no OCR engine available for the requested language" }
$count = Invoke-Ocr $engine $Image $Out
Write-Output ("ok {0} {1}" -f $engine.RecognizerLanguage.LanguageTag, $count)
