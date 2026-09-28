#Requires -Version 5.1
<#
.SYNOPSIS
  打包客户端，并保留腾讯语音识别 secret_id / secret_key 明文。

.DESCRIPTION
  调用 pack.ps1 -KeepSecrets。
  默认输出目录：dist\AronaArchive_Client
  适合本机自用包；勿将产物公开发布或提交仓库。
  打包时不包含 Assets 下的 Photoshop 源文件（*.psd）。

.EXAMPLE
  .\pack_keep_secrets.ps1
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
    $DistDir = Join-Path $Root "dist\AronaArchive_Client"
}

$packArgs = @{
    QtBin      = $QtBin
    DistDir    = $DistDir
    KeepSecrets = $true
}
if ($ExePath) { $packArgs.ExePath = $ExePath }

Write-Host "Mode: KEEP secrets → $DistDir" -ForegroundColor Yellow
& (Join-Path $Root "pack.ps1") @packArgs
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
    exit $LASTEXITCODE
}
