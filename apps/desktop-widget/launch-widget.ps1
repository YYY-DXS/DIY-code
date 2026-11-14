$ErrorActionPreference = "Stop"

$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-Pythonw {
  # 优先用本机自带 Pillow 的运行时（DSH / Codex），其次用 PATH 里的 Python。
  $candidates = @(
    (Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"),
    (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  $onPath = Get-Command pythonw.exe -ErrorAction SilentlyContinue
  if ($onPath) { return $onPath.Source }
  return $null
}

$pythonw = Find-Pythonw
if (-not $pythonw) {
  Write-Host "没有找到 Python。请先安装 Python 3.10 以上版本（安装时勾选 Add to PATH）。"
  exit 1
}

$python = Join-Path (Split-Path -Parent $pythonw) "python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
  if (-not $systemPython) {
    Write-Host "找到了 pythonw，但没有找到 python.exe，无法检查/安装依赖。"
    exit 1
  }
  $python = $systemPython.Source
}

# Pillow 是这个浮窗唯一的第三方依赖：缺了就自动装，不让用户自己猜。
& $python -c "import PIL" *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "首次运行：正在安装 Pillow 图像库（只需一次）..."
  & $python -m pip install --user --disable-pip-version-check pillow
  if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Pillow 安装失败。请检查网络后重试，或手动运行："
    Write-Host "  `"$python`" -m pip install pillow"
    exit 1
  }
}

Start-Process -FilePath $pythonw -ArgumentList @("`"$appRoot\widget.py`"") -WorkingDirectory $appRoot
