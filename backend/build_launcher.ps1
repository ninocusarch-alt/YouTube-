$ErrorActionPreference = 'Stop'

$backendRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $backendRoot '..')).Path
$pythonPath = Join-Path $backendRoot '.venv\Scripts\python.exe'
$specPath = Join-Path $backendRoot 'video_companion.spec'
$buildRoot = Join-Path $backendRoot 'build\video_companion'
$releaseRoot = Join-Path $projectRoot 'release'
$releaseTarget = Join-Path $releaseRoot 'VideoCompanionBackend'
$releaseEnvPath = Join-Path $releaseTarget '.env'
$preservedEnv = $null

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'backend\.venv was not found. Create the project development environment first.'
}

Write-Host '1/5 Running backend tests...'
Push-Location $backendRoot
try {
    if (Test-Path -LiteralPath $releaseEnvPath) {
        $preservedEnv = [System.IO.File]::ReadAllText($releaseEnvPath)
    }

    & $pythonPath -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed. Packaging stopped.' }

    Write-Host '2/5 Installing or updating packaging tools...'
    & $pythonPath -m pip install -r launcher_requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }

    $resolvedBuildRoot = [System.IO.Path]::GetFullPath($buildRoot)
    $resolvedReleaseRoot = [System.IO.Path]::GetFullPath($releaseRoot)
    if (-not $resolvedBuildRoot.StartsWith($backendRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Build directory is outside backend. Packaging stopped.'
    }
    if (-not $resolvedReleaseRoot.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Release directory is outside the project. Packaging stopped.'
    }

    Write-Host '3/5 Cleaning previous launcher build artifacts...'
    if (Test-Path -LiteralPath $buildRoot) {
        Remove-Item -LiteralPath $buildRoot -Recurse -Force
    }
    if (Test-Path -LiteralPath $releaseTarget) {
        Remove-Item -LiteralPath $releaseTarget -Recurse -Force
    }

    New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null

    Write-Host '4/5 Building Windows EXE...'
    & $pythonPath -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $releaseRoot `
        --workpath $buildRoot `
        $specPath
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

    Copy-Item -LiteralPath (Join-Path $backendRoot '.env.example') -Destination (Join-Path $releaseTarget '.env.example')
    Copy-Item -LiteralPath (Join-Path $backendRoot 'launcher\FIRST_RUN.txt') -Destination (Join-Path $releaseTarget 'FIRST_RUN.txt')

    Write-Host '5/5 Scanning the release folder for credentials...'
    $credentialPatterns = @(
        'sk-[A-Za-z0-9_.-]{30,}',
        'gh[pousr]_[A-Za-z0-9_]{20,}'
    )
    $credentialMatches = Get-ChildItem -LiteralPath $releaseTarget -Recurse -File |
        Where-Object { $_.Length -lt 5MB } |
        Select-String -Pattern $credentialPatterns -ErrorAction SilentlyContinue
    if ($credentialMatches) {
        throw 'The release folder may contain a credential. Delivery stopped.'
    }

    $exePath = Join-Path $releaseTarget 'VideoCompanionBackend.exe'
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw 'VideoCompanionBackend.exe was not found after packaging.'
    }

    Write-Host ''
    Write-Host 'Build succeeded:' -ForegroundColor Green
    Write-Host $exePath
}
finally {
    if ($null -ne $preservedEnv) {
        New-Item -ItemType Directory -Path $releaseTarget -Force | Out-Null
        [System.IO.File]::WriteAllText($releaseEnvPath, $preservedEnv, [System.Text.UTF8Encoding]::new($false))
    }
    Pop-Location
}
