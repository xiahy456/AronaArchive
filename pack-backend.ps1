#Requires -Version 5.1
<#
.SYNOPSIS
  Pack the AronaArchive backend into a portable Windows x64 directory and zip.

.DESCRIPTION
  Copies a minimal conda/venv runtime (python.exe + site-packages + native DLLs),
  backend app source, sanitized config, knowledge corpus, and launch scripts into:

    backend\dist\AronaArchive_Backend\
    release\AronaArchive_Backend_v<version>_x64.zip

  Never copies backend/config.yaml (may contain real API keys). The packaged
  config.yaml is generated from config.example.yaml with in-package model paths.

  Create the runtime env first:
    .\setup-backend-pack-env.ps1

.PARAMETER PythonEnv
  Conda env name or an absolute prefix path. Default: arona-backend

.PARAMETER AllowDevEnv
  Allow packing from shittim-chest / a training env. Off by default because
  those envs often include CUDA PyTorch + Unsloth and exceed GitHub size limits.

.PARAMETER IncludeBge
  Copy repo models/bge-small-zh-v1.5 into the package if present.

.PARAMETER IngestKnowledge
  After assembling the package, ingest data/knowledge/corpus into chroma.
  Requires BGE in the package (use -IncludeBge). Sets knowledge.enabled: true.

.PARAMETER SkipZip
  Build the dist folder only.

.PARAMETER DistDir
  Output directory. Default: backend\dist\AronaArchive_Backend

.EXAMPLE
  .\pack-backend.ps1
  .\pack-backend.ps1 -IncludeBge -IngestKnowledge
  .\pack-backend.ps1 -PythonEnv shittim-chest -AllowDevEnv -IncludeBge -IngestKnowledge
#>
[CmdletBinding()]
param(
    [string]$PythonEnv = "arona-backend",
    [switch]$AllowDevEnv,
    [switch]$IncludeBge,
    [switch]$IngestKnowledge,
    [switch]$SkipZip,
    [string]$DistDir = ""
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$PackDir = Join-Path $BackendDir "pack"
$IssPath = Join-Path $Root "frontend\AronaArchive_WindowsClient\AronaArchive.iss"
$BlockedEnvNames = @("shittim-chest")

if (-not $DistDir) {
    $DistDir = Join-Path $BackendDir "dist\AronaArchive_Backend"
}

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message) -ForegroundColor Cyan
}

function Assert-Path([string]$Path, [string]$Hint) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Hint not found: $Path"
    }
}

function Get-BackendPackVersion {
    param([string]$Path)
    if ($Path -and (Test-Path -LiteralPath $Path)) {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        if ($raw -match '#define\s+MyAppVersion\s+"([^"]+)"') {
            return $Matches[1]
        }
    }
    return "unknown"
}

function Get-CondaExe {
    $cmd = Get-Command conda -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        return $cmd.Source
    }
    $candidates = @(
        (Join-Path $env:USERPROFILE "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:USERPROFILE "anaconda3\Scripts\conda.exe"),
        (Join-Path $env:USERPROFILE "Miniconda3\Scripts\conda.exe"),
        "C:\ProgramData\miniconda3\Scripts\conda.exe",
        "C:\ProgramData\anaconda3\Scripts\conda.exe",
        "D:\miniconda3\Scripts\conda.exe",
        "D:\Miniconda3\Scripts\conda.exe",
        "D:\Miniconda\Scripts\conda.exe"
    )
    foreach ($p in $candidates) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            return $p
        }
    }
    return $null
}

function Resolve-PythonPrefix {
    param([string]$NameOrPath)

    if ($NameOrPath -and (Test-Path -LiteralPath (Join-Path $NameOrPath "python.exe"))) {
        return (Resolve-Path -LiteralPath $NameOrPath).Path
    }
    if ($NameOrPath -and (Test-Path -LiteralPath $NameOrPath)) {
        $nested = Join-Path $NameOrPath "python.exe"
        if (Test-Path -LiteralPath $nested) {
            return (Resolve-Path -LiteralPath $NameOrPath).Path
        }
    }

    $conda = Get-CondaExe
    if (-not $conda) {
        throw "Cannot resolve Python env '$NameOrPath' (not a prefix, and conda.exe not found)."
    }
    $info = & $conda env list --json | ConvertFrom-Json
    $match = @($info.envs) | Where-Object { [IO.Path]::GetFileName($_) -eq $NameOrPath } | Select-Object -First 1
    if (-not $match) {
        throw "Conda env '$NameOrPath' not found. Run .\setup-backend-pack-env.ps1 first."
    }
    return $match
}

function Copy-Tree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string[]]$ExtraXd = @()
    )
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $xd = @("__pycache__", ".git", "pkgs", "conda-meta", "include") + $ExtraXd
    $roboArgs = @(
        $Source, $Destination, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/nc", "/ns", "/np",
        "/XD"
    ) + $xd + @("/XF", "*.pyc", "*.pyo", "*.pdb")
    $prevNative = $null
    if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
        $prevNative = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        & robocopy.exe @roboArgs | Out-Null
        $code = $LASTEXITCODE
    }
    finally {
        if ($null -ne $prevNative) {
            $PSNativeCommandUseErrorActionPreference = $prevNative
        }
    }
    # robocopy: 0-7 are success / extra files; 8+ are failures
    if ($code -ge 8) {
        throw "robocopy failed ($code): $Source -> $Destination"
    }
}

Assert-Path $BackendDir "backend directory"
Assert-Path (Join-Path $BackendDir "app\main.py") "backend entry"
Assert-Path (Join-Path $BackendDir "config.example.yaml") "config.example.yaml"
Assert-Path (Join-Path $PackDir "AronaArchive_Backend.bat") "pack template bat"
Assert-Path (Join-Path $PackDir "README.txt") "pack README"

$PackVersion = Get-BackendPackVersion -Path $IssPath
$Prefix = Resolve-PythonPrefix -NameOrPath $PythonEnv
$EnvLeaf = Split-Path -Leaf $Prefix
Write-Host "version: $PackVersion"
Write-Host "python:  $Prefix"

if ((-not $AllowDevEnv) -and ($BlockedEnvNames -contains $EnvLeaf)) {
    throw @"
Refusing to pack from '$EnvLeaf' (likely a training / full-dev env).
Create the minimal runtime with .\setup-backend-pack-env.ps1
or pass -AllowDevEnv if you really want this prefix.
"@
}

$PythonExe = Join-Path $Prefix "python.exe"
Assert-Path $PythonExe "python.exe in pack env"

Write-Step "Preparing $DistDir"
if (Test-Path -LiteralPath $DistDir) {
    Remove-Item -LiteralPath $DistDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

Write-Step "Copying Python runtime"
Copy-Tree -Source $Prefix -Destination (Join-Path $DistDir "python")

Write-Step "Copying backend app"
Copy-Tree -Source (Join-Path $BackendDir "app") -Destination (Join-Path $DistDir "app")

$CorpusSrc = Join-Path $BackendDir "data\knowledge\corpus"
Assert-Path $CorpusSrc "knowledge corpus"
Copy-Tree -Source $CorpusSrc -Destination (Join-Path $DistDir "data\knowledge\corpus")
New-Item -ItemType Directory -Force -Path (Join-Path $DistDir "data\knowledge\chroma") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DistDir "data\memory") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DistDir "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DistDir "models") | Out-Null

Write-Step "Writing sanitized config.yaml"
$example = Get-Content -LiteralPath (Join-Path $BackendDir "config.example.yaml") -Raw -Encoding UTF8
$packConfig = $example.
    Replace("../models/AronaLM-Renderer-V2.4/", "models/AronaLM-Renderer-V2.4/").
    Replace("../models/AronaLM-Generator-V2.0/", "models/AronaLM-Generator-V2.0/").
    Replace('embedding_model_path: "../models/bge-small-zh-v1.5"', 'embedding_model_path: "models/bge-small-zh-v1.5"')
if ($packConfig -match '(?i)sk-[A-Za-z0-9]{10,}') {
    throw "Refusing to pack: config.example.yaml looks like it contains a live API key."
}
Set-Content -LiteralPath (Join-Path $DistDir "config.yaml") -Value $packConfig -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $BackendDir "config.example.yaml") -Destination (Join-Path $DistDir "config.example.yaml")

$readme = (Get-Content -LiteralPath (Join-Path $PackDir "README.txt") -Raw -Encoding UTF8).Replace("{{VERSION}}", $PackVersion)
Set-Content -LiteralPath (Join-Path $DistDir "README.txt") -Value $readme -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $PackDir "AronaArchive_Backend.bat") -Destination (Join-Path $DistDir "AronaArchive_Backend.bat")
Copy-Item -LiteralPath (Join-Path $PackDir "models-README.txt") -Destination (Join-Path $DistDir "models\README.txt")

$vcCandidates = @(
    (Join-Path $Root "frontend\AronaArchive_WindowsClient\dist\AronaArchive_Client_Release\vc_redist.x64.exe"),
    (Join-Path $Root "frontend\AronaArchive_WindowsClient\dist\AronaArchive_Client\vc_redist.x64.exe"),
    (Join-Path $Root "frontend\AronaArchive_WindowsClient\dist\AronaAI_Client_Release\vc_redist.x64.exe"),
    (Join-Path $Root "frontend\AronaArchive_WindowsClient\dist\AronaAI_Client\vc_redist.x64.exe")
)
$vc = $vcCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($vc) {
    Copy-Item -LiteralPath $vc -Destination (Join-Path $DistDir "vc_redist.x64.exe")
    Write-Host "Included vc_redist.x64.exe"
}
else {
    Write-Host "vc_redist.x64.exe not found in client dist; skipped." -ForegroundColor Yellow
}

$BgeSrc = Join-Path $Root "models\bge-small-zh-v1.5"
if ($IncludeBge) {
    if (-not (Test-Path -LiteralPath $BgeSrc)) {
        throw "-IncludeBge set but missing $BgeSrc"
    }
    Write-Step "Copying BGE embedding model"
    Copy-Tree -Source $BgeSrc -Destination (Join-Path $DistDir "models\bge-small-zh-v1.5")
}

if ($IngestKnowledge) {
    $bgeDist = Join-Path $DistDir "models\bge-small-zh-v1.5"
    if (-not (Test-Path -LiteralPath $bgeDist)) {
        throw "-IngestKnowledge requires BGE in the package. Pass -IncludeBge."
    }
    Write-Step "Ingesting knowledge corpus into package chroma"
    $distPython = Join-Path $DistDir "python\python.exe"
    $env:ARONA_BACKEND_DIR = $DistDir
    $env:PYTHONPATH = $DistDir
    $env:PYTHONHOME = Join-Path $DistDir "python"
    $code = @"
from app.config import load_config
from app.knowledge import ingest_corpus
cfg = load_config()
print('embedding', cfg.knowledge_embedding_abs_path)
print('corpus', cfg.knowledge_corpus_abs_path)
n = ingest_corpus(cfg, rebuild=True)
print('chunks', n)
if n <= 0:
    raise SystemExit('ingest produced 0 chunks')
"@
    Push-Location $DistDir
    try {
        & $distPython -c $code
        if ($LASTEXITCODE -ne 0) {
            throw "knowledge ingest failed"
        }
    }
    finally {
        Pop-Location
        Remove-Item Env:ARONA_BACKEND_DIR -ErrorAction SilentlyContinue
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    }
    $enabledConfig = Get-Content -LiteralPath (Join-Path $DistDir "config.yaml") -Raw -Encoding UTF8
    $enabledConfig = [regex]::Replace(
        $enabledConfig,
        '(?m)^(knowledge:\r?\n(?:  .*\r?\n)*?  enabled:\s*)false',
        '${1}true'
    )
    Set-Content -LiteralPath (Join-Path $DistDir "config.yaml") -Value $enabledConfig -Encoding UTF8
}

$ArtifactDir = Join-Path $Root "release"
$ZipPath = Join-Path $ArtifactDir "AronaArchive_Backend_v${PackVersion}_x64.zip"
if (-not $SkipZip) {
    Write-Step "Zipping portable package"
    New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    $parent = Split-Path -Parent $DistDir
    $leaf = Split-Path -Leaf $DistDir
    Push-Location $parent
    try {
        tar.exe -a -c -f $ZipPath $leaf
        if ($LASTEXITCODE -ne 0) {
            throw "tar.exe failed to create $ZipPath"
        }
    }
    finally {
        Pop-Location
    }
    Write-Host "Zip: $ZipPath"
}

Write-Host ""
Write-Host ("[{0}] Backend pack finished." -f (Get-Date -Format "HH:mm:ss")) -ForegroundColor Green
Write-Host "Dist: $DistDir"
if (-not $SkipZip) {
    Write-Host "Zip:  $ZipPath"
}
