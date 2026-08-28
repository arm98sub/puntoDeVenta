param([string]$Destino = "C:\PuntoDeVenta")

$ErrorActionPreference = "Stop"
$PackageRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$SourceApp = Join-Path $PackageRoot "app"
$TargetRoot = [System.IO.Path]::GetFullPath($Destino)
$Database = Join-Path $TargetRoot "data\ferreteria.db"

if (Get-Process -Name "PuntoDeVenta" -ErrorAction SilentlyContinue) {
    throw "Cierre PuntoDeVenta.exe antes de actualizar. No se modifico ningun archivo."
}
if (-not (Test-Path -LiteralPath (Join-Path $SourceApp "PuntoDeVenta.exe"))) { throw "Paquete incompleto: falta PuntoDeVenta.exe" }
if (-not (Test-Path -LiteralPath (Join-Path $SourceApp "_internal"))) { throw "Paquete incompleto: falta _internal" }
if (-not (Test-Path -LiteralPath $Database)) { throw "No se encontro la base existente: $Database. Se cancelo la actualizacion." }

$BackupDir = Join-Path $TargetRoot "backups\manual"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$Stamp = Get-Date -Format "yyyy-MM-dd_HHmmss_fff"
$BackupPath = Join-Path $BackupDir "pre_update_v1.1.1_$Stamp.db"
Copy-Item -LiteralPath $Database -Destination $BackupPath
if ((Get-Item -LiteralPath $BackupPath).Length -ne (Get-Item -LiteralPath $Database).Length) { throw "El respaldo previo no pudo verificarse" }

# Solo se copian binarios de aplicacion. Nunca se enumeran ni reemplazan data,
# branding, tickets, backups o logs del destino.
Copy-Item -LiteralPath (Join-Path $SourceApp "PuntoDeVenta.exe") -Destination (Join-Path $TargetRoot "PuntoDeVenta.exe") -Force
Copy-Item -LiteralPath (Join-Path $SourceApp "_internal") -Destination $TargetRoot -Recurse -Force

Write-Host "Actualizacion v1.1.1 aplicada."
Write-Host "Base preservada: $Database"
Write-Host "Respaldo previo: $BackupPath"
