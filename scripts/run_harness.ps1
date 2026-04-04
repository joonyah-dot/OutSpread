param(
    [switch]$Fresh,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$remainingArgs = @($ExtraArgs | Where-Object { $_ -and $_ -ne "." })

if ($remainingArgs -contains "--fresh" -or $remainingArgs -contains "-fresh" -or $remainingArgs -contains "fresh") {
    $Fresh = $true
    $remainingArgs = @($remainingArgs | Where-Object { $_ -ne "--fresh" -and $_ -ne "-fresh" -and $_ -ne "fresh" })
}

if ($remainingArgs.Count -gt 0) {
    throw "Unknown arguments: $($remainingArgs -join ', '). Supported: -Fresh or --fresh"
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    Write-Host "==> $Name"
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Name (exit code $LASTEXITCODE)"
    }
}

function Invoke-ConfigureWithFallback {
    param(
        [Parameter(Mandatory = $true)][string]$BuildDir,
        [Parameter(Mandatory = $true)][bool]$ForceFresh
    )

    $buildPath = Join-Path (Get-Location) $BuildDir
    if ($ForceFresh -and (Test-Path $buildPath)) {
        Write-Host "==> Fresh build requested; removing '$buildPath'"
        Remove-Item -Recurse -Force $buildPath
    }

    Write-Host "==> Configure CMake"
    cmake -S . -B $BuildDir
    if ($LASTEXITCODE -eq 0) {
        return
    }

    if (-not (Test-Path $buildPath)) {
        throw "Step failed: Configure CMake (exit code $LASTEXITCODE)"
    }

    Write-Warning "Initial configure failed. Retrying once with a fresh '$BuildDir' directory."
    Remove-Item -Recurse -Force $buildPath
    cmake -S . -B $BuildDir
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: Configure CMake retry (exit code $LASTEXITCODE)"
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot

try {
    $buildDir = "build"
    $config = "Release"

    Invoke-ConfigureWithFallback -BuildDir $buildDir -ForceFresh $Fresh.IsPresent
    Invoke-Step "Build Release" { cmake --build $buildDir --config $config }

    $harness = Get-ChildItem -Path $buildDir -Recurse -File -Filter "vst3_harness.exe" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $harness) {
        throw "Could not find vst3_harness.exe under '$buildDir'."
    }

    $plugin = Get-ChildItem -Path $buildDir -Recurse -Directory -Filter "*.vst3" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $plugin) {
        throw "Could not find a built .vst3 plugin directory under '$buildDir'."
    }

    $generatedDir = Join-Path $repoRoot "tests/_generated"
    $artifactsRoot = Join-Path $repoRoot "artifacts"
    New-Item -ItemType Directory -Force -Path $generatedDir | Out-Null
    New-Item -ItemType Directory -Force -Path $artifactsRoot | Out-Null

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $runOutDir = Join-Path $artifactsRoot $timestamp
    New-Item -ItemType Directory -Force -Path $runOutDir | Out-Null

    Invoke-Step "Generate test WAVs" {
        python scripts/gen_test_wavs.py --outdir $generatedDir --sr 48000 --seconds 2.0 --channels 2
    }

    Invoke-Step "Dump plugin params" {
        & $harness.FullName dump-params --plugin $plugin.FullName
    }

    $dryImpulse = Join-Path $generatedDir "impulse.wav"
    $wetFile = Join-Path $runOutDir "wet.wav"

    Invoke-Step "Render offline (impulse -> wet.wav)" {
        & $harness.FullName render --plugin $plugin.FullName --in $dryImpulse --outdir $runOutDir --sr 48000 --bs 256 --ch 2
    }

    Invoke-Step "Analyze + null test" {
        & $harness.FullName analyze --dry $dryImpulse --wet $wetFile --outdir $runOutDir --auto-align --null
    }

    Write-Host ""
    Write-Host "Harness completed successfully."
    Write-Host "Harness : $($harness.FullName)"
    Write-Host "Plugin  : $($plugin.FullName)"
    Write-Host "Output  : $runOutDir"
}
catch {
    Write-Error $_
    exit 1
}
finally {
    Pop-Location
}
