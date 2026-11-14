<#
    电脑管家 PcToolkit - 快捷方式模块
    在桌面 / 开始菜单创建「电脑管家」快捷方式（带图标，启动时不弹黑框）。
    这个文件本身没有副作用，可以被图形界面和命令行脚本共同加载。
#>

function New-ToolkitShortcut {
    param(
        # 快捷方式放哪个目录；不填 = 用当前用户的桌面
        [string]$TargetDir,
        # 是否同时在开始菜单建一个
        [switch]$IncludeStartMenu,
        [string]$Name = '电脑管家',
        # 工具根目录；不填 = 本模块所在目录的上一层
        [string]$ToolRoot
    )

    if (-not $ToolRoot) {
        $ToolRoot = Split-Path -Parent $PSScriptRoot
    }
    $result = [pscustomobject]@{
        Ok = $false
        Made = @()
        Failed = @()
        Exe = ''
        Gui = ''
        Message = ''
    }

    $gui = Join-Path $ToolRoot 'PcToolkitGui.ps1'
    $ico = Join-Path $ToolRoot 'assets\app.ico'
    if (-not (Test-Path -LiteralPath $gui)) {
        $result.Message = "找不到界面脚本：$gui"
        return $result
    }
    $result.Gui = $gui

    # 优先用 PowerShell 7（装了就用），否则用系统自带的 5.1
    $exe = 'powershell.exe'
    try {
        $pf = [Environment]::GetFolderPath('ProgramFiles')
        if ($pf) {
            $pwsh7 = Join-Path $pf 'PowerShell\7\pwsh.exe'
            if (Test-Path -LiteralPath $pwsh7) { $exe = $pwsh7 }
        }
    } catch { }
    $result.Exe = $exe

    $argumentLine = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $gui + '"'

    $dirs = New-Object System.Collections.ArrayList
    if ($TargetDir) {
        [void]$dirs.Add($TargetDir)
    } else {
        $desktop = [Environment]::GetFolderPath('Desktop')
        if ($desktop) { [void]$dirs.Add($desktop) }
    }
    if ($IncludeStartMenu) {
        $startMenu = Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'Microsoft\Windows\Start Menu\Programs'
        if ($startMenu -and (Test-Path -LiteralPath $startMenu)) { [void]$dirs.Add($startMenu) }
    }
    if ($dirs.Count -eq 0) {
        $result.Message = '找不到桌面目录，无法创建快捷方式。'
        return $result
    }

    try {
        $shell = New-Object -ComObject WScript.Shell
    } catch {
        $result.Message = "无法创建快捷方式对象：$($_.Exception.Message)"
        return $result
    }

    $made = New-Object System.Collections.ArrayList
    $failed = New-Object System.Collections.ArrayList
    foreach ($dir in $dirs) {
        $lnkPath = Join-Path $dir ($Name + '.lnk')
        try {
            if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            $lnk = $shell.CreateShortcut($lnkPath)
            $lnk.TargetPath = $exe
            $lnk.Arguments = $argumentLine
            $lnk.WorkingDirectory = $ToolRoot
            if (Test-Path -LiteralPath $ico) { $lnk.IconLocation = "$ico,0" }
            $lnk.Description = '电脑管家 PcToolkit：体检 / 修复运行环境 / 整理文件 / 清理垃圾'
            $lnk.WindowStyle = 7
            $lnk.Save()
            if (Test-Path -LiteralPath $lnkPath) { [void]$made.Add($lnkPath) }
            else { [void]$failed.Add("$lnkPath（文件没有生成）") }
        } catch {
            [void]$failed.Add("$lnkPath（$($_.Exception.Message)）")
        }
    }

    $result.Made = @($made)
    $result.Failed = @($failed)
    $result.Ok = ($made.Count -gt 0)
    if (-not $result.Ok) {
        $result.Message = '快捷方式创建失败，常见原因：桌面被安全软件保护、或者权限不足。'
    }
    return $result
}

function Test-ToolkitShortcut {
    <#  读取快捷方式里的信息，用来验证是否真的建好了  #>
    param([Parameter(Mandatory)][string]$LnkPath)
    if (-not (Test-Path -LiteralPath $LnkPath)) { return $null }
    try {
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut($LnkPath)
        return [pscustomobject]@{
            Path = $LnkPath; Target = $lnk.TargetPath; Arguments = $lnk.Arguments
            WorkingDirectory = $lnk.WorkingDirectory; IconLocation = $lnk.IconLocation
            Description = $lnk.Description; WindowStyle = $lnk.WindowStyle
        }
    } catch { return $null }
}
