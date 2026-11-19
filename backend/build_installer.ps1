$ErrorActionPreference = 'Stop'

$backendRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $backendRoot '..')).Path
$pythonPath = Join-Path $backendRoot '.venv\Scripts\python.exe'
$launcherBuildScript = Join-Path $backendRoot 'build_launcher.ps1'
$payloadRoot = Join-Path $backendRoot 'build\installer_payload'
$installerWork = Join-Path $backendRoot 'build\video_companion_installer'
$releaseRoot = Join-Path $projectRoot 'release'
$backendRelease = Join-Path $releaseRoot 'VideoCompanionBackend'
$installerRelease = Join-Path $releaseRoot 'installer'
$specPath = Join-Path $backendRoot 'video_companion_installer.spec'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'backend\.venv was not found.'
}

Write-Host '1/6 Building the application payload...'
& powershell -NoProfile -ExecutionPolicy Bypass -File $launcherBuildScript
if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }

$resolvedPayload = [System.IO.Path]::GetFullPath($payloadRoot)
$resolvedInstallerWork = [System.IO.Path]::GetFullPath($installerWork)
$resolvedInstallerRelease = [System.IO.Path]::GetFullPath($installerRelease)
foreach ($path in @($resolvedPayload, $resolvedInstallerWork)) {
    if (-not $path.StartsWith($backendRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Installer build path is outside backend.'
    }
}
if (-not $resolvedInstallerRelease.StartsWith($releaseRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Installer output path is outside release.'
}

Write-Host '2/6 Preparing a credential-free payload...'
foreach ($path in @($payloadRoot, $installerWork, $installerRelease)) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}
New-Item -ItemType Directory -Path $payloadRoot -Force | Out-Null
New-Item -ItemType Directory -Path $installerRelease -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $backendRelease '_internal') -Destination (Join-Path $payloadRoot '_internal') -Recurse
Copy-Item -LiteralPath (Join-Path $backendRelease 'VideoCompanionBackend.exe') -Destination $payloadRoot
Copy-Item -LiteralPath (Join-Path $backendRelease '.env.example') -Destination $payloadRoot
Copy-Item -LiteralPath (Join-Path $backendRelease 'FIRST_RUN.txt') -Destination $payloadRoot
Copy-Item -LiteralPath (Join-Path $backendRoot 'installer\INSTALL_CHROME_EXTENSION.html') -Destination $payloadRoot
New-Item -ItemType Directory -Path (Join-Path $payloadRoot 'extension') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'extension\dist') -Destination (Join-Path $payloadRoot 'extension\dist') -Recurse
$payloadLiveWeb = Join-Path $payloadRoot 'live\web'
New-Item -ItemType Directory -Path $payloadLiveWeb -Force | Out-Null
Copy-Item -Path (Join-Path $backendRoot 'live\web\*') -Destination $payloadLiveWeb -Recurse -Force

if (Test-Path -LiteralPath (Join-Path $payloadRoot '.env')) {
    throw 'A private .env file entered the installer payload.'
}
$credentialMatches = Get-ChildItem -LiteralPath $payloadRoot -Recurse -File |
    Where-Object { $_.Length -lt 5MB } |
    Select-String -Pattern @('sk-[A-Za-z0-9_.-]{30,}', 'gh[pousr]_[A-Za-z0-9_]{20,}') -ErrorAction SilentlyContinue
if ($credentialMatches) { throw 'The installer payload may contain a credential.' }

Write-Host '3/6 Running all tests...'
Push-Location $backendRoot
try {
    & $pythonPath -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }

    Write-Host '4/6 Building the one-click installer...'
    $env:VIDEO_COMPANION_INSTALLER_PAYLOAD = $payloadRoot
    & $pythonPath -m PyInstaller --noconfirm --clean --distpath $installerRelease --workpath $installerWork $specPath
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
}
finally {
    Remove-Item Env:\VIDEO_COMPANION_INSTALLER_PAYLOAD -ErrorAction SilentlyContinue
    Pop-Location
}

$setupPath = Join-Path $installerRelease 'VideoCompanionSetup.exe'
if (-not (Test-Path -LiteralPath $setupPath)) { throw 'VideoCompanionSetup.exe was not produced.' }

Write-Host '5/6 Verifying the embedded payload...'
& $setupPath --self-test
if ($LASTEXITCODE -ne 0) { throw 'Installer self-test failed.' }

Write-Host '6/6 Installer ready:' -ForegroundColor Green
Write-Host $setupPath
