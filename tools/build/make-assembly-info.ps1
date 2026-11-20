# 生成 C# 的 AssemblyInfo（产品名/版本元数据），供 csc 编译时使用。
# 代码签名要求每个可执行文件都带产品名与版本信息，缺了会被 SignPath 拒绝。
# 用法：
#   ./make-assembly-info.ps1 -OutFile launcher-info.cs -ProductName "DeepSeek Hub Panel" -Version 2.0.8
param(
    [Parameter(Mandatory = $true)][string]$OutFile,
    [Parameter(Mandatory = $true)][string]$ProductName,
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Title = "",
    [string]$Description = "",
    [string]$CompanyName = "YYY-DXS",
    [string]$Copyright = "MIT License",
    [string]$Guid = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Title)) { $Title = $ProductName }
if ([string]::IsNullOrWhiteSpace($Description)) { $Description = $ProductName }
if ([string]::IsNullOrWhiteSpace($Guid)) { $Guid = [guid]::NewGuid().ToString().ToUpper() }

$parts = @($Version.Trim().TrimStart('v') -split '[.\-+]' | Where-Object { $_ -match '^\d+$' })
while ($parts.Count -lt 4) { $parts += "0" }
$ver = ($parts[0..3] | ForEach-Object { [int]$_ }) -join "."

$content = @"
// 由 tools/build/make-assembly-info.ps1 生成，请勿手改
using System.Reflection;
using System.Runtime.InteropServices;

[assembly: AssemblyTitle("$Title")]
[assembly: AssemblyDescription("$Description")]
[assembly: AssemblyCompany("$CompanyName")]
[assembly: AssemblyProduct("$ProductName")]
[assembly: AssemblyCopyright("$Copyright")]
[assembly: ComVisible(false)]
[assembly: Guid("$Guid")]
[assembly: AssemblyVersion("$ver")]
[assembly: AssemblyFileVersion("$ver")]
"@

$path = if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path (Get-Location) $OutFile }
[System.IO.File]::WriteAllText($path, $content, (New-Object System.Text.UTF8Encoding($true)))
Write-Host "AssemblyInfo 已生成：$OutFile（$ProductName $ver）"
