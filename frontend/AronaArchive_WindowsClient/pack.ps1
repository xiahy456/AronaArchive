#Requires -Version 5.1
<#
.SYNOPSIS
  Package AronaArchive_WindowsClient into a portable release folder.

.DESCRIPTION
  Copies the Release exe, runs windeployqt for Qt runtime DLLs/plugins,
  and copies Assets / Config / Dict into a portable package folder.
  Photoshop source files (*.psd) under Assets are omitted from the package.
  Config/config.json is taken from the project (relative paths expected);
  secrets are sanitized and machine-local program_path is dropped unless
  -KeepSecrets is set.

.PARAMETER QtBin
  Path to Qt bin directory containing windeployqt.exe.
  Default: D:\Qt68\6.5.3\msvc2019_64\bin

.PARAMETER DistDir
  Output package directory. If omitted:
    -KeepSecrets  → <script_dir>\dist\AronaArchive_Client
    (default)     → <script_dir>\dist\AronaArchive_Client_Release

.PARAMETER ExePath
  Path to Release exe. Default: <script_dir>\x64\Release\AronaArchive_WindowsClient.exe
  (falls back to AronaAI_WindowsClient.exe or AronaAI_Spine_WindowsClient.exe if the new name is not built yet).
  The packaged copy is always named AronaArchive_WindowsClient.exe.

.PARAMETER KeepSecrets
  If set, keep tencent_speech_recognizer secrets from the source config.
  By default secrets are replaced with placeholders.

.EXAMPLE
  .\pack.ps1

.EXAMPLE
  .\pack.ps1 -KeepSecrets -QtBin "D:\Qt68\6.5.3\msvc2019_64\bin"

.NOTES
  推荐入口（两种密钥策略，输出到不同目录）：
    .\pack_keep_secrets.ps1      → dist\AronaArchive_Client
    .\pack_sanitize_secrets.ps1  → dist\AronaArchive_Client_Release
#>
[CmdletBinding()]
param(
    [string]$QtBin = "D:\Qt68\6.5.3\msvc2019_64\bin",
    [string]$DistDir = "",
    [string]$ExePath = "",
    [switch]$KeepSecrets
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
if (-not $DistDir) {
    if ($KeepSecrets) {
        $DistDir = Join-Path $Root "dist\AronaArchive_Client"
    }
    else {
        $DistDir = Join-Path $Root "dist\AronaArchive_Client_Release"
    }
}
$DistExeName = "AronaArchive_WindowsClient.exe"
if (-not $ExePath) {
    $candidates = @(
        (Join-Path $Root "x64\Release\AronaArchive_WindowsClient.exe"),
        (Join-Path $Root "x64\Release\AronaAI_WindowsClient.exe"),
        (Join-Path $Root "x64\Release\AronaAI_Spine_WindowsClient.exe")
    )
    $ExePath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $ExePath) { $ExePath = $candidates[0] }
}

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-Path([string]$Path, [string]$Hint) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Hint not found: $Path"
    }
}

function Copy-Tree([string]$Source, [string]$Destination, [string[]]$Exclude = @()) {
    Assert-Path $Source "Source"
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    $parent = Split-Path -Parent $Destination
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
    # Copy-Item -Recurse -Exclude only filters the top level; strip leftovers after copy.
    foreach ($pattern in $Exclude) {
        Get-ChildItem -LiteralPath $Destination -Filter $pattern -Recurse -File -ErrorAction SilentlyContinue |
            Remove-Item -Force
    }
}

# --- Preconditions -----------------------------------------------------------
Write-Step "Checking inputs"
Assert-Path $ExePath "Release executable"
$WinDeployQt = Join-Path $QtBin "windeployqt.exe"
Assert-Path $WinDeployQt "windeployqt.exe (pass -QtBin if Qt is elsewhere)"

$AssetsSrc = Join-Path $Root "Assets"
$ConfigSrc = Join-Path $Root "Config"
$DictSrc   = Join-Path $Root "Dict"
$FontSrc   = Join-Path $Root "Assets\ProgramAssets\font\Blueaka"

Assert-Path $AssetsSrc "Assets"
Assert-Path $ConfigSrc "Config"
Assert-Path $DictSrc "Dict"
Assert-Path $FontSrc "Blueaka font directory (Assets/ProgramAssets/font/Blueaka)"

$SourceConfig = Join-Path $ConfigSrc "config.json"
if (-not (Test-Path -LiteralPath $SourceConfig)) {
    $SourceConfig = Join-Path $ConfigSrc "config.example.json"
    Write-Host "config.json missing; using config.example.json" -ForegroundColor Yellow
}
Assert-Path $SourceConfig "Config JSON"

# --- Clean / create dist -----------------------------------------------------
Write-Step "Preparing package directory: $DistDir"
if (Test-Path -LiteralPath $DistDir) {
    # Stop processes launched from this package dir so DLLs are not locked.
    $distFull = (Resolve-Path -LiteralPath $DistDir).Path.TrimEnd('\')
    $locked = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ExecutablePath -and
            $_.ExecutablePath.StartsWith($distFull, [System.StringComparison]::OrdinalIgnoreCase)
        }
    foreach ($proc in $locked) {
        Write-Host "Stopping locked process PID $($proc.ProcessId): $($proc.ExecutablePath)" -ForegroundColor Yellow
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($locked) {
        Start-Sleep -Milliseconds 500
    }

    try {
        Remove-Item -LiteralPath $DistDir -Recurse -Force -ErrorAction Stop
    }
    catch {
        throw @"
Cannot clean package directory (files locked):
  $DistDir

Close AronaArchive_WindowsClient.exe (and any explorer preview locking DLLs), then retry.
Original error: $($_.Exception.Message)
"@
    }
}
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

Copy-Item -LiteralPath $ExePath -Destination (Join-Path $DistDir $DistExeName) -Force
Write-Host "Copied $(Split-Path $ExePath -Leaf) → $DistExeName"
$ExeName = $DistExeName

# --- windeployqt -------------------------------------------------------------
Write-Step "Running windeployqt"
# Help windeployqt locate VC++ redistributables when run outside a VS Developer shell.
if (-not $env:VCINSTALLDIR) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path -LiteralPath $vswhere) {
        $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
        if ($vsPath) {
            $vcCandidates = Get-ChildItem -Path (Join-Path $vsPath "VC\Redist\MSVC") -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending
            if ($vcCandidates) {
                $env:VCINSTALLDIR = (Join-Path $vsPath "VC\")
                Write-Host "VCINSTALLDIR=$($env:VCINSTALLDIR)"
            }
        }
    }
}
$deployArgs = @(
    "--release",
    "--compiler-runtime",
    "--opengl",
    "--multimedia",
    "--websockets",
    (Join-Path $DistDir $ExeName)
)
& $WinDeployQt @deployArgs
if ($LASTEXITCODE -ne 0) {
    throw "windeployqt failed with exit code $LASTEXITCODE"
}

# --- Assets / Dict -----------------------------------------------------------
Write-Step "Copying Assets, Dict"
Copy-Tree $AssetsSrc (Join-Path $DistDir "Assets") -Exclude "*.psd"
Copy-Tree $DictSrc   (Join-Path $DistDir "Dict")
Write-Host "Assets copied (*.psd source files excluded)."

# --- Config ------------------------------------------------------------------
Write-Step "Writing Config/config.json"
$configDir = Join-Path $DistDir "Config"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

# Keep source formatting (2-space indent like config.example.json); avoid ConvertTo-Json.
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$raw = [System.IO.File]::ReadAllText($SourceConfig, $utf8NoBom)

# Drop machine-local program shortcuts from the portable package.
$raw = [regex]::Replace($raw, ',\r?\n  "program_path"\s*:\s*\{[\s\S]*?\r?\n  \}', '')

if (-not $KeepSecrets) {
    # MatchEvaluator + single-quoted result: keep literal ${TENCENT_...} placeholders.
    $raw = [regex]::Replace($raw, '"secret_id"\s*:\s*"[^"]*"', { '"secret_id": "${TENCENT_SECRET_ID}"' })
    $raw = [regex]::Replace($raw, '"secret_key"\s*:\s*"[^"]*"', { '"secret_key": "${TENCENT_SECRET_KEY}"' })
    Write-Host "Sanitized tencent_speech_recognizer secrets (use -KeepSecrets to retain)." -ForegroundColor Yellow
}

$outConfig = Join-Path $configDir "config.json"
[System.IO.File]::WriteAllText($outConfig, $raw.TrimEnd() + "`n", $utf8NoBom)

$exampleSrc = Join-Path $ConfigSrc "config.example.json"
if (Test-Path -LiteralPath $exampleSrc) {
    Copy-Item -LiteralPath $exampleSrc -Destination (Join-Path $configDir "config.example.json") -Force
}

# --- Summary -----------------------------------------------------------------
Write-Step "Done"
Write-Host "Package ready at:" -ForegroundColor Green
Write-Host "  $DistDir"
Write-Host ""
Write-Host "Launch:"
Write-Host "  cd `"$DistDir`""
Write-Host "  .\$ExeName"
Write-Host ""
Write-Host "Edit Config\config.json for websocket_url / TTS host before distributing."
if (-not $KeepSecrets) {
    Write-Host "Fill tencent secrets in Config\config.json if ASR is needed."
}
