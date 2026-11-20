# 生成 PyInstaller 的版本资源文件（VSVersionInfo）
# 用途：让构建出来的 exe 带有产品名/版本元数据——代码签名（SignPath 等）的硬性要求。
# 用法：
#   ./make-version-info.ps1 -OutFile win-version.txt -ProductName "DSH-Plugin-Pulse" -Version 2.0.8
param(
    [Parameter(Mandatory = $true)][string]$OutFile,
    [Parameter(Mandatory = $true)][string]$ProductName,
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$FileDescription = "",
    [string]$CompanyName = "YYY-DXS",
    [string]$Copyright = "MIT License"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($FileDescription)) { $FileDescription = $ProductName }

# 2.0.8 -> (2,0,8,0)
$parts = @($Version.Trim().TrimStart('v') -split '[.\-+]' | Where-Object { $_ -match '^\d+$' })
while ($parts.Count -lt 4) { $parts += "0" }
$parts = $parts[0..3]
$ver = ($parts | ForEach-Object { [int]$_ }) -join ","
$verText = $parts -join "."

$content = @"
# 由 tools/build/make-version-info.ps1 生成，请勿手改
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($ver),
    prodvers=($ver),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u'$CompanyName'),
            StringStruct(u'FileDescription', u'$FileDescription'),
            StringStruct(u'FileVersion', u'$verText'),
            StringStruct(u'InternalName', u'$ProductName'),
            StringStruct(u'LegalCopyright', u'$Copyright'),
            StringStruct(u'OriginalFilename', u'$ProductName.exe'),
            StringStruct(u'ProductName', u'$ProductName'),
            StringStruct(u'ProductVersion', u'$verText')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@

$path = if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path (Get-Location) $OutFile }
[System.IO.File]::WriteAllText($path, $content, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "版本资源已生成：$OutFile（$ProductName $verText）"
