param(
    [switch]$IncludeRealData,
    [ValidateSet("FERRETERIA", "GENERAL")][string]$Edition = "FERRETERIA"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Spec = Join-Path $ProjectRoot "PuntoDeVenta.spec"
$BuildTarget = Join-Path $ProjectRoot "build\PuntoDeVenta"
$DistTarget = Join-Path $ProjectRoot "dist\PuntoDeVenta"

function Assert-SafeChild([string]$Path, [string]$Parent) {
    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $resolvedParent = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    if (-not $resolvedPath.StartsWith($resolvedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Ruta fuera del proyecto: $resolvedPath"
    }
}

if (-not (Test-Path -LiteralPath $Python)) { throw "No existe el entorno virtual: $Python" }
if ($IncludeRealData) {
    & $Python (Join-Path $ProjectRoot "create_prebuild_backup.py")
    if ($LASTEXITCODE -ne 0) { throw "Falló el respaldo obligatorio previo al build" }
}
Assert-SafeChild $BuildTarget $ProjectRoot
Assert-SafeChild $DistTarget $ProjectRoot
if (Test-Path -LiteralPath $BuildTarget) { Remove-Item -LiteralPath $BuildTarget -Recurse -Force }
if (Test-Path -LiteralPath $DistTarget) { Remove-Item -LiteralPath $DistTarget -Recurse -Force }

$PreviousEdition = $env:PUNTO_VENTA_EDITION
$env:PUNTO_VENTA_EDITION = $Edition
try { & $Python -m PyInstaller --clean --noconfirm $Spec }
finally {
    if ($null -eq $PreviousEdition) { Remove-Item Env:PUNTO_VENTA_EDITION -ErrorAction SilentlyContinue }
    else { $env:PUNTO_VENTA_EDITION = $PreviousEdition }
}
if ($LASTEXITCODE -ne 0) { throw "PyInstaller terminó con código $LASTEXITCODE" }

foreach ($relative in @("data\branding", "tickets", "backups\manual", "backups\automatic", "logs")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $DistTarget $relative) | Out-Null
}
Copy-Item -LiteralPath (Join-Path $ProjectRoot "INSTALAR_EN_OTRA_PC.txt") -Destination $DistTarget
Copy-Item -LiteralPath (Join-Path $ProjectRoot "crear_acceso_directo.ps1") -Destination $DistTarget

if ($IncludeRealData) {
    & $Python (Join-Path $ProjectRoot "prepare_distribution_data.py") `
        --source (Join-Path $ProjectRoot $(if ($Edition -eq "GENERAL") { "data\punto_venta.db" } else { "data\ferreteria.db" })) `
        --destination (Join-Path $DistTarget $(if ($Edition -eq "GENERAL") { "data\punto_venta.db" } else { "data\ferreteria.db" })) `
        --confirm-real-data
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron preparar los datos reales" }
}

Write-Host "Build terminado: $DistTarget"
