#Requires -Version 5.1
<#
.SYNOPSIS
  打包客户端，并将腾讯语音识别密钥替换为占位符（脱敏，不明文写出）。

.DESCRIPTION
  调用 pack.ps1（默认脱敏）。secret_id / secret_key 写入为
  ${TENCENT_SECRET_ID} / ${TENCENT_SECRET_KEY}。
  默认输出目录：dist\AronaArchive_Client_Release
  适合对外分发。
  打包时不包含 Assets 下的 Photoshop 源文件（*.psd）。

.EXAMPLE
  .\pack_sanitize_secrets.ps1
#>
[CmdletBinding()]
param(
    [string]$QtBin = "D:\Qt68\6.5.3\msvc2019_64\bin",
    [string]$DistDir = "",
    [string]$ExePath = ""
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
if (-not $DistDir) {
    $DistDir = Join-Path $Root "dist\AronaArchive_Client_Release"
}

$packArgs = @{
    QtBin   = $QtBin
    DistDir = $DistDir
}
if ($ExePath) { $packArgs.ExePath = $ExePath }

Write-Host "Mode: SANITIZE secrets → $DistDir" -ForegroundColor Cyan
& (Join-Path $Root "pack.ps1") @packArgs
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
    exit $LASTEXITCODE
}
