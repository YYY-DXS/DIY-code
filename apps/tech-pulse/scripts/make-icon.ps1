param(
  [Parameter(Mandatory = $true)][string]$Output
)

Add-Type -AssemblyName System.Drawing

$bitmap = New-Object System.Drawing.Bitmap 256, 256
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.Clear([System.Drawing.Color]::Transparent)

$path = New-Object System.Drawing.Drawing2D.GraphicsPath
$radius = 56
$path.AddArc(8, 8, $radius, $radius, 180, 90)
$path.AddArc(192, 8, $radius, $radius, 270, 90)
$path.AddArc(192, 192, $radius, $radius, 0, 90)
$path.AddArc(8, 192, $radius, $radius, 90, 90)
$path.CloseFigure()

$background = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 17, 25, 20))
$graphics.FillPath($background, $path)

$pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 217, 255, 87), 19)
$pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
$pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
$pen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
$points = @(
  (New-Object System.Drawing.PointF(42, 132)),
  (New-Object System.Drawing.PointF(77, 132)),
  (New-Object System.Drawing.PointF(99, 74)),
  (New-Object System.Drawing.PointF(132, 188)),
  (New-Object System.Drawing.PointF(157, 104)),
  (New-Object System.Drawing.PointF(175, 132)),
  (New-Object System.Drawing.PointF(215, 132))
)
$graphics.DrawLines($pen, $points)

$directory = Split-Path -Parent $Output
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$bitmap.Save($Output, [System.Drawing.Imaging.ImageFormat]::Png)

$pen.Dispose()
$background.Dispose()
$path.Dispose()
$graphics.Dispose()
$bitmap.Dispose()
