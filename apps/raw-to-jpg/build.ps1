$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = Split-Path -Parent $projectRoot
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$windowsBase = "C:\Windows\Microsoft.NET\assembly\GAC_MSIL\WindowsBase\v4.0_4.0.0.0__31bf3856ad364e35\WindowsBase.dll"
$presentationCore = "C:\Windows\Microsoft.NET\assembly\GAC_64\PresentationCore\v4.0_4.0.0.0__31bf3856ad364e35\PresentationCore.dll"
$systemXaml = "C:\Windows\Microsoft.NET\assembly\GAC_MSIL\System.Xaml\v4.0_4.0.0.0__b77a5c561934e089\System.Xaml.dll"

$outputPath = Join-Path $workspaceRoot "outputs\RAW转JPG.exe"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null

& $csc `
    /nologo `
    /target:winexe `
    /platform:anycpu `
    /optimize+ `
    /langversion:5 `
    /utf8output `
    "/out:$outputPath" `
    "/win32icon:$projectRoot\build\app.ico" `
    "/win32manifest:$projectRoot\src\app.manifest" `
    /reference:System.dll `
    /reference:System.Core.dll `
    /reference:System.Drawing.dll `
    /reference:System.Windows.Forms.dll `
    "/reference:$windowsBase" `
    "/reference:$presentationCore" `
    "/reference:$systemXaml" `
    "$projectRoot\src\AssemblyInfo.cs" `
    "$projectRoot\src\ConversionCore.cs" `
    "$projectRoot\src\Raw2JpgStudio.cs"

if ($LASTEXITCODE -ne 0) {
    throw "编译失败，退出码：$LASTEXITCODE"
}

Write-Host "已生成：$outputPath"
