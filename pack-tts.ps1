#Requires -Version 5.1
<#
.SYNOPSIS
  Pack Arona-owned GPT-SoVITS overlay files into release/ (no Python runtime).

.DESCRIPTION
  在仓库根目录执行。把 tts/ 下本仓库跟踪的启动脚本、文档、launch_api.py、
  voices.json 与参考音频打成 zip。不含 runtime、上游 clone、官方整合包、模型与预训练。

  压缩包根目录是 tts/，解压到仓库根即可。

    .\pack-tts.ps1
    → release\AronaArchive_GPTSoVITS_v<version>_x64.zip

.PARAMETER SkipZip
  只组装临时目录，不写 zip。

.EXAMPLE
  .\pack-tts.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$TtsRoot = Join-Path $Root "tts"
$IssPath = Join-Path $Root "frontend\AronaArchive_WindowsClient\AronaArchive.iss"
$ArtifactDir = Join-Path $Root "release"
$StageRoot = Join-Path $ArtifactDir ".tts-pack-stage"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message) -ForegroundColor Cyan
}

function Get-PackVersion {
    param([string]$Path)
    if ($Path -and (Test-Path -LiteralPath $Path)) {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        if ($raw -match '#define\s+MyAppVersion\s+"([^"]+)"') {
            return $Matches[1]
        }
    }
    return "unknown"
}

function Copy-RelFile {
    param(
        [Parameter(Mandatory = $true)][string]$Relative,
        [switch]$Optional
    )
    $src = Join-Path $Root $Relative
    if (-not (Test-Path -LiteralPath $src)) {
        if ($Optional) {
            Write-Host "  skip missing: $Relative" -ForegroundColor Yellow
            return
        }
        throw "Missing overlay file: $src"
    }
    $dst = Join-Path $StageRoot $Relative
    $parent = Split-Path -Parent $dst
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $src -Destination $dst -Force
    Write-Host "  $Relative"
}

if (-not (Test-Path -LiteralPath $TtsRoot)) {
    throw "tts/ not found: $TtsRoot"
}

$PackVersion = Get-PackVersion -Path $IssPath
$ZipPath = Join-Path $ArtifactDir "AronaArchive_GPTSoVITS_v${PackVersion}_x64.zip"

Write-Step "Staging Arona GPT-SoVITS overlay (scripts + ref audio; no runtime)"
if (Test-Path -LiteralPath $StageRoot) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $StageRoot -Force | Out-Null

$FixedFiles = @(
    "tts\README.md",
    "tts\gpt-sovits\DEPLOY.md",
    "tts\gpt-sovits\go-apiv2.bat",
    "tts\gpt-sovits\go-apiv2.sh",
    "tts\gpt-sovits\watch-apiv2.ps1",
    "tts\gpt-sovits\watch-apiv2.sh",
    "tts\gpt-sovits-minimal\DEPLOY.md",
    "tts\gpt-sovits-minimal\go-api.bat",
    "tts\gpt-sovits-minimal\go-api.ps1",
    "tts\gpt-sovits-minimal\watch-api.ps1",
    "tts\gpt-sovits-minimal\launch_api.py",
    "tts\gpt-sovits-minimal\pack-runtime.ps1",
    "tts\gpt-sovits-minimal\config\voices.json"
)

foreach ($rel in $FixedFiles) {
    Copy-RelFile -Relative $rel
}

$RefDir = Join-Path $Root "tts\gpt-sovits\ref_audio\Arona"
if (Test-Path -LiteralPath $RefDir) {
    Get-ChildItem -LiteralPath $RefDir -File | Where-Object {
        $_.Extension -match '^\.(ogg|wav|mp3|txt)$'
    } | ForEach-Object {
        $rel = $_.FullName.Substring($Root.Length).TrimStart('\', '/')
        Copy-RelFile -Relative $rel
    }
}
else {
    Write-Host "  skip missing: tts\gpt-sovits\ref_audio\Arona" -ForegroundColor Yellow
}

$staged = @(Get-ChildItem -LiteralPath $StageRoot -Recurse -File)
if ($staged.Count -lt 1) {
    throw "Stage is empty; nothing to pack."
}
Write-Host ("Staged {0} files." -f $staged.Count) -ForegroundColor Green

if ($SkipZip) {
    Write-Host "SkipZip: left stage at $StageRoot"
    return
}

New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Write-Step "Zipping -> $ZipPath"
$tar = Get-Command tar.exe -ErrorAction SilentlyContinue
Push-Location $StageRoot
try {
    if ($tar) {
        & tar.exe -a -c -f $ZipPath "tts"
        if ($LASTEXITCODE -ne 0) {
            throw "tar.exe failed ($LASTEXITCODE)"
        }
    }
    else {
        Compress-Archive -Path (Join-Path $StageRoot "tts") -DestinationPath $ZipPath -Force
    }
}
finally {
    Pop-Location
}

Remove-Item -LiteralPath $StageRoot -Recurse -Force
Write-Host ""
Write-Host ("[{0}] TTS overlay pack finished." -f (Get-Date -Format "HH:mm:ss")) -ForegroundColor Green
Write-Host "Zip: $ZipPath"
Write-Host "Extract into the repository root."
