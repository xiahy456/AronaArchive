#Requires -Version 5.1
<#
.SYNOPSIS
  Copy the gpt-sovits-minimal conda/venv prefix into this directory's runtime/.

.DESCRIPTION
  Produces tts/gpt-sovits-minimal/runtime/python.exe (same layout as official
  tts/gpt-sovits/runtime). watch-api.ps1 and start-all.ps1 prefer this interpreter.
  Does not copy weights, HuBERT, BERT, or ref audio.

  Create / fix the source env first (CUDA Torch), then:

    .\pack-runtime.ps1
    .\pack-runtime.ps1 -Zip

.PARAMETER EnvName
  Conda env name. Ignored when -Prefix is set. Default: gpt-sovits-minimal

.PARAMETER Prefix
  Absolute env prefix that already contains python.exe.

.PARAMETER Zip
  Also write release/AronaArchive_GPTSoVITS_minimal_runtime_x64.zip
  (archive root is runtime/). Extract into tts/gpt-sovits-minimal/.

.EXAMPLE
  .\pack-runtime.ps1
  .\pack-runtime.ps1 -Prefix D:\Miniconda\envs\gpt-sovits-minimal -Zip
#>
[CmdletBinding()]
param(
    [string]$EnvName = "gpt-sovits-minimal",
    [string]$Prefix = "",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$GptDir = $PSScriptRoot
$TtsRoot = Split-Path -Parent $GptDir
$RepoRoot = Split-Path -Parent $TtsRoot
$DestDir = Join-Path $GptDir "runtime"
$DestPy = Join-Path $DestDir "python.exe"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message) -ForegroundColor Cyan
}

function Get-CondaExe {
    $cmd = Get-Command conda -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
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
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return $null
}

function Resolve-PythonPrefix {
    param([string]$ExplicitPrefix, [string]$Name)
    if ($ExplicitPrefix) {
        $py = Join-Path $ExplicitPrefix "python.exe"
        if (-not (Test-Path -LiteralPath $py)) {
            throw "Prefix has no python.exe: $ExplicitPrefix"
        }
        return (Resolve-Path -LiteralPath $ExplicitPrefix).Path
    }
    $conda = Get-CondaExe
    if (-not $conda) {
        throw "conda.exe not found. Pass -Prefix to an env that contains python.exe."
    }
    $info = & $conda env list --json | ConvertFrom-Json
    $match = @($info.envs) | Where-Object { [IO.Path]::GetFileName($_) -eq $Name } | Select-Object -First 1
    if (-not $match) {
        throw "Conda env '$Name' not found. See DEPLOY.md."
    }
    return $match
}

function Copy-Tree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $xd = @("__pycache__", ".git", "pkgs", "conda-meta", "include")
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
    if ($code -ge 8) {
        throw "robocopy failed ($code): $Source -> $Destination"
    }
}

function Test-CudaTorch {
    param([string]$PythonExe, [string]$HomeDir)
    $prevHome = $env:PYTHONHOME
    $prevPath = $env:PYTHONPATH
    try {
        $env:PYTHONHOME = $HomeDir
        $env:PYTHONPATH = ""
        $out = & $PythonExe -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'n/a')"
        if ($LASTEXITCODE -ne 0) {
            throw "python exited $LASTEXITCODE"
        }
        $lines = @($out | Where-Object { $_ })
        Write-Host ($lines -join " | ")
        if ($lines.Count -lt 2 -or $lines[1] -notmatch '^(True|true)$') {
            throw "torch.cuda.is_available() is not True. Refusing to pack a CPU runtime. See DEPLOY.md."
        }
    }
    finally {
        if ($null -eq $prevHome) { Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue } else { $env:PYTHONHOME = $prevHome }
        if ($null -eq $prevPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $prevPath }
    }
}

$Prefix = Resolve-PythonPrefix -ExplicitPrefix $Prefix -Name $EnvName
$SourcePy = Join-Path $Prefix "python.exe"
if (-not (Test-Path -LiteralPath $SourcePy)) {
    throw "python.exe not found in $Prefix"
}

$prefixFull = (Resolve-Path -LiteralPath $Prefix).Path
$destParent = (Resolve-Path -LiteralPath $GptDir).Path
if ($prefixFull.TrimEnd('\') -ieq $DestDir.TrimEnd('\')) {
    throw "Source prefix is already $DestDir. Refusing to copy onto itself."
}

Write-Step "Source env"
Write-Host "  Prefix: $Prefix"
Write-Host "  Dest:   $DestDir"

Write-Step "Checking source CUDA Torch"
Test-CudaTorch -PythonExe $SourcePy -HomeDir $Prefix

Write-Step "Copying prefix -> runtime (this can take several minutes)"
if (Test-Path -LiteralPath $DestDir) {
    Remove-Item -LiteralPath $DestDir -Recurse -Force
}
Copy-Tree -Source $Prefix -Destination $DestDir
if (-not (Test-Path -LiteralPath $DestPy)) {
    throw "Copy finished but $DestPy is missing."
}

Write-Step "Checking runtime CUDA Torch"
Test-CudaTorch -PythonExe $DestPy -HomeDir $DestDir
Write-Host "Packed runtime: $DestPy" -ForegroundColor Green

if ($Zip) {
    $releaseDir = Join-Path $RepoRoot "release"
    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
    $zipPath = Join-Path $releaseDir "AronaArchive_GPTSoVITS_minimal_runtime_x64.zip"
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Write-Step "Zipping runtime -> $zipPath"
    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($tar) {
        Push-Location $GptDir
        try {
            & tar.exe -a -cf $zipPath "runtime"
            if ($LASTEXITCODE -ne 0) {
                throw "tar.exe failed ($LASTEXITCODE)"
            }
        }
        finally {
            Pop-Location
        }
    }
    else {
        Compress-Archive -Path $DestDir -DestinationPath $zipPath -Force
    }
    Write-Host "Zip: $zipPath" -ForegroundColor Green
    Write-Host "Extract the runtime folder into tts/gpt-sovits-minimal/ so python.exe is tts\gpt-sovits-minimal\runtime\python.exe."
}
