$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$windowsBase = "C:\Windows\Microsoft.NET\assembly\GAC_MSIL\WindowsBase\v4.0_4.0.0.0__31bf3856ad364e35\WindowsBase.dll"
$presentationCore = "C:\Windows\Microsoft.NET\assembly\GAC_64\PresentationCore\v4.0_4.0.0.0__31bf3856ad364e35\PresentationCore.dll"
$systemXaml = "C:\Windows\Microsoft.NET\assembly\GAC_MSIL\System.Xaml\v4.0_4.0.0.0__b77a5c561934e089\System.Xaml.dll"
$testExe = Join-Path $env:TEMP "Raw2JpgStudioTests.exe"

& $csc `
    /nologo `
    /target:exe `
    /platform:anycpu `
    /optimize+ `
    /langversion:5 `
    /utf8output `
    "/out:$testExe" `
    /reference:System.dll `
    /reference:System.Core.dll `
    /reference:System.Drawing.dll `
    "/reference:$windowsBase" `
    "/reference:$presentationCore" `
    "/reference:$systemXaml" `
    "$projectRoot\src\ConversionCore.cs" `
    "$projectRoot\tests\ConversionCoreTests.cs"

if ($LASTEXITCODE -ne 0) {
    throw "测试编译失败，退出码：$LASTEXITCODE"
}

& $testExe
if ($LASTEXITCODE -ne 0) {
    throw "测试失败，退出码：$LASTEXITCODE"
}
