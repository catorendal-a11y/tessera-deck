<#
.SYNOPSIS
  Starts Libre Hardware Monitor at every sign-in with administrator rights, so the CPU temperature, power and
  fan speed on the status screen are always there. Windows asks for confirmation once, now.

.DESCRIPTION
  Libre Hardware Monitor needs administrator rights for its sensor driver. Instead of a Windows prompt at every
  sign-in, this registers a scheduled task named "Tessera Sensors" that starts it at logon with the highest
  privileges for your user only, and starts it now. -Once only starts it now (setup_sensors.ps1 uses it).
  -Remove deletes the task and the firewall rule again.
  Run through Tessera.cmd --sensors (and --sensors-off).

  The elevated copy is downloaded again, checked against the pinned SHA-256 and installed in
  %ProgramFiles%\Tessera\LibreHardwareMonitor, where only administrators can write. The copy in host\sensors is
  never started elevated: the Tessera folder is writable by every program you run, so a program could swap the exe
  or put a DLL beside it and have the task start it as administrator at the next sign-in, without a prompt.
#>
param(
    [switch]$Remove,
    [switch]$Once
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lhm_release.ps1')
$TaskName = 'Tessera Sensors'
$FirewallRule = 'Tessera-Sensors-Block-Network'
$Base = Join-Path $env:ProgramFiles 'Tessera'
$InstallDir = Join-Path $Base 'LibreHardwareMonitor'
$Exe = Join-Path $InstallDir 'LibreHardwareMonitor.exe'

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$IsAdmin = ([Security.Principal.WindowsPrincipal]$Identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin) {
    Write-Host 'Windows will ask for permission to continue as administrator ...'
    # Bypass for this script only, as in Tessera.cmd: a script from a downloaded zip is refused under RemoteSigned
    $Arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    if ($Remove) { $Arguments += '-Remove' }
    if ($Once) { $Arguments += '-Once' }
    try { Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $Arguments -Wait }
    catch { Write-Host 'Cancelled. Nothing was changed.'; Start-Sleep -Seconds 3 }
    return
}

# Administrators and SYSTEM may change the folder, users may only read and run it. Inheritance is cut so no
# broader rule from above applies.
function Protect-AdminOnly([string]$Dir) {
    & icacls.exe $Dir /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null
    if ($LASTEXITCODE) { throw "Could not set the permissions of $Dir." }
}

# Downloads, verifies and extracts inside the locked folder, so nothing unelevated can swap a file between the
# hash check and the copy (the user's TEMP folder would allow that).
function Install-AdminCopy {
    New-Item -ItemType Directory -Path $Base -Force | Out-Null
    Protect-AdminOnly $Base
    if (Test-Path $Exe) { return }
    $Stage = Join-Path $Base ('staging-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Stage | Out-Null
    try {
        $Zip = Join-Path $Stage 'LibreHardwareMonitor.zip'
        Save-LhmZip $Zip
        $Fresh = Join-Path $Stage 'LibreHardwareMonitor'
        Expand-Archive -Path $Zip -DestinationPath $Fresh
        Get-ChildItem -Path $Fresh -Recurse -File | Unblock-File
        Write-LhmConfig $Fresh
        if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
        Move-Item -Path $Fresh -Destination $InstallDir
    }
    finally {
        Remove-Item -Recurse -Force $Stage -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path $Exe)) { throw "LibreHardwareMonitor.exe was not found in $InstallDir after extraction." }
}

# Libre Hardware Monitor listens on every interface. Block rules win over allow rules, so a click on Allow in a
# firewall prompt cannot open the sensor data to the network. Loopback, which Tessera uses, is not filtered.
function Add-FirewallBlock {
    if (Get-NetFirewallRule -Name $FirewallRule -ErrorAction SilentlyContinue) { return }
    New-NetFirewallRule -Name $FirewallRule -DisplayName 'Tessera Sensors: block network access to Libre Hardware Monitor' `
        -Direction Inbound -Action Block -Protocol TCP -LocalPort $LhmPort -Profile Any | Out-Null
}

try {
    if ($Remove) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Remove-NetFirewallRule -Name $FirewallRule -ErrorAction SilentlyContinue
        Write-Host "Removed the scheduled task '$TaskName'. Libre Hardware Monitor no longer starts by itself."
        Write-Host "Its files stay in $InstallDir."
        return
    }
    Install-AdminCopy
    Add-FirewallBlock
    if (-not $Once) {
        $User = "$($Identity.Name)"
        $Action = New-ScheduledTaskAction -Execute $Exe -WorkingDirectory $InstallDir
        $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
        $Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest
        $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
        Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal `
            -Settings $Settings -Force | Out-Null
    }
    if (-not (Get-Process -Name 'LibreHardwareMonitor' -ErrorAction SilentlyContinue)) {
        if ($Once) { Start-Process -FilePath $Exe -WorkingDirectory $InstallDir }
        else { Start-ScheduledTask -TaskName $TaskName }
    }
    if ($Once) { Write-Host 'Done. Libre Hardware Monitor is running. Tessera.cmd --sensors starts it at every sign-in.' }
    else { Write-Host 'Done. Libre Hardware Monitor starts at every sign-in and is running now.' }
    Write-Host 'The temperatures appear on the status screen within a few seconds.'
}
catch {
    Write-Host "Could not finish: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Start-Sleep -Seconds 4  # also after -Remove, which returns early: the window would close before it can be read
}
