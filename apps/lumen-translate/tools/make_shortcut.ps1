# Create a desktop (and optional Start Menu) shortcut for Lumen Translate.
#   powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
#   powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1 -StartMenu -Remove
#
# ASCII-only on purpose (Windows PowerShell 5.1 decodes .ps1 with the OEM code page).
param(
    [string]$Name = "Lumen Translate",
    [switch]$StartMenu,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if (-not (Test-Path $target)) {
    $target = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
}
if (-not $target) { throw "pythonw.exe not found (neither the bundled runtime nor PATH)" }

$entry = Join-Path $root "main.pyw"
$icon = Join-Path $root "assets\lumen.ico"

$desktop = [Environment]::GetFolderPath("Desktop")
$paths = @((Join-Path $desktop "$Name.lnk"))
if ($StartMenu) {
    $programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    $paths += (Join-Path $programs "$Name.lnk")
}

$shell = New-Object -ComObject WScript.Shell
foreach ($path in $paths) {
    if ($Remove) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
            Write-Output "removed: $path"
        }
        continue
    }
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $target
    $shortcut.Arguments = '"' + $entry + '"'
    $shortcut.WorkingDirectory = $root
    if (Test-Path $icon) { $shortcut.IconLocation = "$icon,0" }
    $shortcut.Description = "Lumen Translate - desktop translator with selection popup"
    $shortcut.Save()
    Write-Output "created: $path"
    Write-Output "  target: $target"
    Write-Output "  args  : `"$entry`""
}
