param([string]$ExePath = (Join-Path $PSScriptRoot "PuntoDeVenta.exe"))

$ExePath = [System.IO.Path]::GetFullPath($ExePath)
if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) { throw "No existe el ejecutable: $ExePath" }
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Punto de Venta.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.WorkingDirectory = Split-Path -Parent $ExePath
$Shortcut.Description = "Punto de Venta 1.1.0"
$Shortcut.Save()
Write-Host "Acceso directo creado: $ShortcutPath"
