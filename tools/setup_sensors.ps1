<#
.SYNOPSIS
  Installs Libre Hardware Monitor (free, MPL-2.0) next to Tessera so the status screen
  can show CPU/GPU temperature, power and fan speed.

.DESCRIPTION
  Downloads the official release, verifies its SHA-256, extracts it to host\sensors and
  enables its remote web server (port 8085, read by Tessera on 127.0.0.1). Libre Hardware
  Monitor needs administrator rights for its sensor driver, so it is then started through
  enable_sensors.ps1 -Once: Windows asks for confirmation (UAC) once, and the elevated copy
  runs from a verified install in Program Files, never from this folder, which any program
  you run can change.
#>
param(
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lhm_release.ps1')

$Root = Split-Path -Parent $PSScriptRoot
$InstallDir = Join-Path $Root 'host\sensors\LibreHardwareMonitor'
$Exe = Join-Path $InstallDir 'LibreHardwareMonitor.exe'

if (-not (Test-Path $Exe)) {
    # Downloaded files are untrusted: use a fresh, empty directory of our own, and extract into a fresh directory
    # too, so files that were already in InstallDir do not end up beside the new ones.
    $Work = Join-Path ([System.IO.Path]::GetTempPath()) ("tessera-lhm-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Work | Out-Null
    try {
        $Zip = Join-Path $Work 'LibreHardwareMonitor.zip'
        Save-LhmZip $Zip
        $Fresh = Join-Path $Work 'LibreHardwareMonitor'
        Expand-Archive -Path $Zip -DestinationPath $Fresh
        Get-ChildItem -Path $Fresh -Recurse -File | Unblock-File
        if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
        New-Item -ItemType Directory -Path (Split-Path -Parent $InstallDir) -Force | Out-Null
        Move-Item -Path $Fresh -Destination $InstallDir
    }
    finally {
        Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $Exe)) {
    throw "LibreHardwareMonitor.exe was not found in $InstallDir after extraction."
}
Write-LhmConfig $InstallDir

if ($NoStart) { return }

if (Get-Process -Name 'LibreHardwareMonitor' -ErrorAction SilentlyContinue) {
    Write-Host 'Libre Hardware Monitor is already running. Restart it to apply the settings.'
    return
}
# Not Start-Process $Exe -Verb RunAs: that would run whatever sits in InstallDir with administrator rights.
& (Join-Path $PSScriptRoot 'enable_sensors.ps1') -Once
