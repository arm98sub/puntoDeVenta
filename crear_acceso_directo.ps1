param([string]$ExePath = (Join-Path $PSScriptRoot "PuntoDeVenta.exe"))

$ExePath = [System.IO.Path]::GetFullPath($ExePath)
if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) { throw "No existe el ejecutable: $ExePath" }
$Desktop = [Environment]::GetFolderPath("Desktop")
$MetadataPath=Join-Path $PSScriptRoot "version.json"
$Metadata=if (Test-Path -LiteralPath $MetadataPath) { Get-Content -LiteralPath $MetadataPath -Raw | ConvertFrom-Json } else { $null }
$IsGeneral=$Metadata -and $Metadata.edition -eq "GENERAL"
$DisplayName=if ($IsGeneral) { "PuntoDeVenta General" } else { "Ferretería POS" }
$Version=if ($Metadata -and $Metadata.version) { $Metadata.version } else { "desconocida" }
$ShortcutPath = Join-Path $Desktop ($DisplayName + ".lnk")
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.WorkingDirectory = Split-Path -Parent $ExePath
$Shortcut.Description = "$DisplayName $Version"
$Shortcut.Save()
Write-Host "Acceso directo creado: $ShortcutPath"
