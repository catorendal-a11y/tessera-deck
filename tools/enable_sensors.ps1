<#
.SYNOPSIS
  Starts Libre Hardware Monitor at every sign-in with administrator rights, so the CPU temperature, power and
  fan speed on the status screen are always there. Windows asks for confirmation once, now.

.DESCRIPTION
  Libre Hardware Monitor needs administrator rights for its sensor driver. Instead of a Windows prompt at every
  sign-in, this registers a scheduled task named "Tessera Sensors" that starts it at logon with the highest
  privileges for your user only, and starts it now. -Remove deletes the task again.
  Run through Tessera.cmd --sensors (and --sensors-off).
#>
param(
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$TaskName = 'Tessera Sensors'
$Root = Split-Path -Parent $PSScriptRoot
$InstallDir = Join-Path $Root 'host\sensors\LibreHardwareMonitor'
$Exe = Join-Path $InstallDir 'LibreHardwareMonitor.exe'

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$IsAdmin = ([Security.Principal.WindowsPrincipal]$Identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin) {
    Write-Host 'Windows will ask for permission to continue as administrator ...'
    $Arguments = @('-NoProfile', '-ExecutionPolicy', 'RemoteSigned', '-File', "`"$PSCommandPath`"")
    if ($Remove) { $Arguments += '-Remove' }
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $Arguments -Wait
    return
}

try {
    if ($Remove) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed the scheduled task '$TaskName'. Libre Hardware Monitor no longer starts by itself."
        return
    }
    if (-not (Test-Path $Exe)) {
        throw "Libre Hardware Monitor is not installed in $InstallDir. Run tools\setup_sensors.ps1 first."
    }
    $User = "$($Identity.Name)"
    $Action = New-ScheduledTaskAction -Execute $Exe -WorkingDirectory $InstallDir
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
    $Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal `
        -Settings $Settings -Force | Out-Null
    if (-not (Get-Process -Name 'LibreHardwareMonitor' -ErrorAction SilentlyContinue)) {
        Start-ScheduledTask -TaskName $TaskName
    }
    Write-Host "Done. Libre Hardware Monitor starts at every sign-in and is running now."
    Write-Host 'The temperatures appear on the status screen within a few seconds.'
}
catch {
    Write-Host "Could not finish: $($_.Exception.Message)" -ForegroundColor Red
}
Start-Sleep -Seconds 4
