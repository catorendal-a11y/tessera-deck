<#
.SYNOPSIS
  Installs Libre Hardware Monitor (free, MPL-2.0) next to Tessera so the status screen
  can show CPU/GPU temperature, power and fan speed.

.DESCRIPTION
  Downloads the official release, verifies its SHA-256, extracts it to host\sensors,
  enables its remote web server (http://127.0.0.1:8085/data.json) and starts it elevated.
  Libre Hardware Monitor needs administrator rights for its sensor driver, so Windows asks
  for confirmation (UAC) when it starts.
#>
param(
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'

$Version = 'v0.9.6'
$Url = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/$Version/LibreHardwareMonitor.zip"
$ExpectedSha256 = '086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001'
$Root = Split-Path -Parent $PSScriptRoot
$InstallDir = Join-Path $Root 'host\sensors\LibreHardwareMonitor'
$Exe = Join-Path $InstallDir 'LibreHardwareMonitor.exe'
$Config = Join-Path $InstallDir 'LibreHardwareMonitor.config'

if (-not (Test-Path $Exe)) {
    # Downloaded files are untrusted: use a fresh, empty directory of our own.
    $Work = Join-Path ([System.IO.Path]::GetTempPath()) ("tessera-lhm-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Work | Out-Null
    $Zip = Join-Path $Work 'LibreHardwareMonitor.zip'
    Write-Host "Downloading Libre Hardware Monitor $Version ..."
    Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
    $Actual = (Get-FileHash -Path $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $ExpectedSha256) {
        Remove-Item -Recurse -Force $Work
        throw "SHA-256 mismatch. Expected $ExpectedSha256 but got $Actual. Nothing was installed."
    }
    Write-Host "SHA-256 verified: $Actual"
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Expand-Archive -Path $Zip -DestinationPath $InstallDir -Force
    Get-ChildItem -Path $InstallDir -Recurse -File | Unblock-File
    Remove-Item -Recurse -Force $Work
}

if (-not (Test-Path $Exe)) {
    throw "LibreHardwareMonitor.exe was not found in $InstallDir after extraction."
}

# Remote web server on loopback only, start minimized to the tray.
$Settings = [ordered]@{
    runWebServerMenuItem = 'true'
    listenerPort         = '8085'
    startMinMenuItem     = 'true'
    minTrayMenuItem      = 'true'
    minCloseMenuItem     = 'true'
}
$Lines = @('<?xml version="1.0" encoding="utf-8"?>', '<configuration>', '  <appSettings>')
foreach ($Name in $Settings.Keys) { $Lines += "    <add key=`"$Name`" value=`"$($Settings[$Name])`" />" }
$Lines += @('  </appSettings>', '</configuration>')
[System.IO.File]::WriteAllLines($Config, $Lines, [System.Text.UTF8Encoding]::new($false))
Write-Host "Configured: $Config"

if ($NoStart) { return }

if (Get-Process -Name 'LibreHardwareMonitor' -ErrorAction SilentlyContinue) {
    Write-Host 'Libre Hardware Monitor is already running. Restart it to apply the settings.'
    return
}
Write-Host 'Starting Libre Hardware Monitor (approve the Windows prompt) ...'
Start-Process -FilePath $Exe -Verb RunAs -WorkingDirectory $InstallDir
