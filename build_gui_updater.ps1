param([ValidateSet("FERRETERIA", "GENERAL")][string]$Edition = "FERRETERIA")

$ErrorActionPreference="Stop"
$Root=[System.IO.Path]::GetFullPath($PSScriptRoot)
$Python=Join-Path $Root ".venv\Scripts\python.exe"
$Stage=Join-Path $Root "build\gui_updater_1.1.4"
$PackageSuffix=if ($Edition -eq "GENERAL") { "_GENERAL" } else { "" }
$Package=Join-Path $Root ("dist\PuntoDeVenta_Actualizacion_1.1.4" + $PackageSuffix)

function Assert-SafeChild([string]$Path,[string]$Parent) {
    $child=[System.IO.Path]::GetFullPath($Path)
    $base=[System.IO.Path]::GetFullPath($Parent).TrimEnd('\')+'\'
    if (-not $child.StartsWith($base,[System.StringComparison]::OrdinalIgnoreCase)) { throw "Ruta insegura: $child" }
}

Assert-SafeChild $Stage $Root
Assert-SafeChild $Package $Root
if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
if (Test-Path -LiteralPath $Package) { Remove-Item -LiteralPath $Package -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage,$Package,(Join-Path $Package "payload") | Out-Null

$PreviousEdition=$env:PUNTO_VENTA_EDITION
$env:PUNTO_VENTA_EDITION=$Edition
try {
    & $Python -m PyInstaller --clean --noconfirm --distpath (Join-Path $Stage "updater_dist") --workpath (Join-Path $Stage "updater_work") (Join-Path $Root "ActualizarPuntoDeVenta.spec")
    if ($LASTEXITCODE -ne 0) { throw "Fallo el build del actualizador" }
    & $Python -m PyInstaller --clean --noconfirm --distpath (Join-Path $Stage "pos_dist") --workpath (Join-Path $Stage "pos_work") (Join-Path $Root "PuntoDeVenta.spec")
    if ($LASTEXITCODE -ne 0) { throw "Fallo el build del POS" }
}
finally {
    if ($null -eq $PreviousEdition) { Remove-Item Env:PUNTO_VENTA_EDITION -ErrorAction SilentlyContinue }
    else { $env:PUNTO_VENTA_EDITION=$PreviousEdition }
}

$UpdaterBuild=Join-Path $Stage "updater_dist\ActualizarPuntoDeVenta"
$PosBuild=Join-Path $Stage "pos_dist\PuntoDeVenta"
Copy-Item -LiteralPath (Join-Path $UpdaterBuild "ActualizarPuntoDeVenta.exe") -Destination $Package
Copy-Item -LiteralPath (Join-Path $UpdaterBuild "_updater_internal") -Destination $Package -Recurse
Copy-Item -LiteralPath (Join-Path $PosBuild "PuntoDeVenta.exe") -Destination (Join-Path $Package "payload")
Copy-Item -LiteralPath (Join-Path $PosBuild "_internal") -Destination (Join-Path $Package "payload") -Recurse
$VersionData=Get-Content -LiteralPath (Join-Path $Root "version.json") -Raw | ConvertFrom-Json
$VersionData.edition=$Edition
$VersionData | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Package "version.json") -Encoding utf8
Copy-Item -LiteralPath (Join-Path $Root "ACTUALIZAR_PUNTO_DE_VENTA.txt") -Destination $Package

$forbidden=Get-ChildItem -LiteralPath $Package -Recurse -File | Where-Object { $_.Name -eq "ferreteria.db" -or $_.Extension -eq ".db" }
if ($forbidden) { throw "El paquete contiene una base de datos prohibida" }
foreach ($name in @("data","tickets","backups","logs")) {
    if (Test-Path -LiteralPath (Join-Path $Package "payload\$name")) { throw "El payload contiene datos: $name" }
}
Write-Host "Actualizador grafico listo: $Package"
