#Requires -Version 5.1
<#
.SYNOPSIS
  依次执行前端两种打包：保留密钥包 + 脱敏发布包，再打 zip 与 Inno Setup 安装包。

.DESCRIPTION
  在项目根目录调用：
    1) frontend\AronaArchive_WindowsClient\pack_keep_secrets.ps1
       → dist\AronaArchive_Client（明文密钥，本机自用）
    2) frontend\AronaArchive_WindowsClient\pack_sanitize_secrets.ps1
       → dist\AronaArchive_Client_Release（脱敏，对外分发）
    3) 将 AronaArchive_Client_Release 打成 zip
       → release\AronaArchive_WindowsClient_v<version>_x64.zip
    4) Inno Setup ISCC 编译 AronaArchive.iss
       → release\AronaArchive_WindowsClient_v<version>_x64_Setup.exe（基于脱敏发布包）

  任一脚本失败则立即退出。

.PARAMETER QtBin
  传给两个打包脚本的 Qt bin 路径。

.PARAMETER ExePath
  可选；传给两个打包脚本的 exe 路径。省略则由各自脚本 / pack.ps1 自动检测。

.PARAMETER InnoISCC
  Inno Setup 编译器 ISCC.exe 路径。

.PARAMETER SkipInstaller
  若指定，跳过安装包编译（仍会打 zip）。

.PARAMETER SkipZip
  若指定，跳过 zip 便携包。

.EXAMPLE
  .\pack-client.ps1
  .\pack-client.ps1 -QtBin "D:\Qt68\6.5.3\msvc2019_64\bin"
#>
[CmdletBinding()]
param(
    [string]$QtBin = "D:\Qt68\6.5.3\msvc2019_64\bin",
    [string]$ExePath = "",
    [string]$InnoISCC = "D:\Inno\Inno Setup 7\ISCC.exe",
    [switch]$SkipInstaller,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$ClientRoot = Join-Path $PSScriptRoot "frontend\AronaArchive_WindowsClient"
$KeepScript = Join-Path $ClientRoot "pack_keep_secrets.ps1"
$SanitizeScript = Join-Path $ClientRoot "pack_sanitize_secrets.ps1"

foreach ($p in @($KeepScript, $SanitizeScript)) {
    if (-not (Test-Path -LiteralPath $p)) {
        throw "Missing pack script: $p"
    }
}

$packArgs = @{ QtBin = $QtBin }
if ($ExePath) { $packArgs.ExePath = $ExePath }

function Invoke-PackScript {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)][hashtable]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )
    Write-Host ""
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Label) -ForegroundColor Cyan
    & $ScriptPath @Arguments
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        exit $LASTEXITCODE
    }
}

function Get-ClientPackVersion {
    param([Parameter(Mandatory = $true)][string]$IssPath)
    if (Test-Path -LiteralPath $IssPath) {
        $raw = Get-Content -LiteralPath $IssPath -Raw -Encoding UTF8
        if ($raw -match '#define\s+MyAppVersion\s+"([^"]+)"') {
            return $Matches[1]
        }
    }
    return "unknown"
}

Invoke-PackScript -ScriptPath $KeepScript -Arguments $packArgs -Label "Pack KEEP secrets"
Invoke-PackScript -ScriptPath $SanitizeScript -Arguments $packArgs -Label "Pack SANITIZE secrets"

$IssPath = Join-Path $ClientRoot "AronaArchive.iss"
$ReleaseDir = Join-Path $ClientRoot "dist\AronaArchive_Client_Release"
$ArtifactDir = Join-Path $PSScriptRoot "release"
$PackVersion = Get-ClientPackVersion -IssPath $IssPath
$ZipPath = Join-Path $ArtifactDir "AronaArchive_WindowsClient_v${PackVersion}_x64.zip"

if ((-not $SkipZip) -or (-not $SkipInstaller)) {
    New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
}

if (-not $SkipZip) {
    if (-not (Test-Path -LiteralPath $ReleaseDir)) {
        throw "Release package not found: $ReleaseDir"
    }
    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }

    Write-Host ""
    Write-Host ("[{0}] Zip portable package" -f (Get-Date -Format "HH:mm:ss")) -ForegroundColor Cyan
    Compress-Archive -Path $ReleaseDir -DestinationPath $ZipPath -CompressionLevel Optimal
    Write-Host "Zip: $ZipPath"
}

if (-not $SkipInstaller) {
    if (-not (Test-Path -LiteralPath $InnoISCC)) {
        throw "ISCC.exe not found: $InnoISCC"
    }
    if (-not (Test-Path -LiteralPath $IssPath)) {
        throw "Missing Inno Setup script: $IssPath"
    }

    Write-Host ""
    Write-Host ("[{0}] Compile Inno Setup installer" -f (Get-Date -Format "HH:mm:ss")) -ForegroundColor Cyan
    Push-Location $ClientRoot
    try {
        & $InnoISCC "/O$ArtifactDir" ".\AronaArchive.iss"
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host ("[{0}] Client packs finished." -f (Get-Date -Format "HH:mm:ss")) -ForegroundColor Green
if ((-not $SkipZip) -or (-not $SkipInstaller)) {
    Write-Host "Artifacts: $ArtifactDir"
}
