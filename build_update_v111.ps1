param()

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Spec = Join-Path $ProjectRoot "PuntoDeVenta.spec"
$StageRoot = Join-Path $ProjectRoot "build\update_v1.1.1"
$PackageRoot = Join-Path $ProjectRoot "dist\PuntoDeVenta_v1.1.1"
$AppRoot = Join-Path $PackageRoot "app"

function Assert-SafeChild([string]$Path, [string]$Parent) {
    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $resolvedParent = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    if (-not $resolvedPath.StartsWith($resolvedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Ruta fuera del proyecto: $resolvedPath"
    }
}

if (-not (Test-Path -LiteralPath $Python)) { throw "No existe el entorno virtual: $Python" }
Assert-SafeChild $StageRoot $ProjectRoot
Assert-SafeChild $PackageRoot $ProjectRoot
if (Test-Path -LiteralPath $StageRoot) { Remove-Item -LiteralPath $StageRoot -Recurse -Force }
if (Test-Path -LiteralPath $PackageRoot) { Remove-Item -LiteralPath $PackageRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $StageRoot,$AppRoot | Out-Null

& $Python -m PyInstaller --clean --noconfirm --distpath (Join-Path $StageRoot "dist") --workpath (Join-Path $StageRoot "work") $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller termino con codigo $LASTEXITCODE" }

$BuiltApp = Join-Path $StageRoot "dist\PuntoDeVenta"
Copy-Item -LiteralPath (Join-Path $BuiltApp "PuntoDeVenta.exe") -Destination $AppRoot
Copy-Item -LiteralPath (Join-Path $BuiltApp "_internal") -Destination $AppRoot -Recurse
Copy-Item -LiteralPath (Join-Path $ProjectRoot "actualizar_v1.1.1.ps1") -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "ACTUALIZAR_A_V1.1.1.txt") -Destination $PackageRoot

$forbidden = @(
    (Join-Path $PackageRoot "data\ferreteria.db"),
    (Join-Path $AppRoot "data\ferreteria.db"),
    (Join-Path $PackageRoot "tickets"),
    (Join-Path $PackageRoot "backups"),
    (Join-Path $PackageRoot "logs")
)
foreach ($path in $forbidden) { if (Test-Path -LiteralPath $path) { throw "El paquete contiene datos prohibidos: $path" } }
Write-Host "Paquete de actualizacion seguro: $PackageRoot"
