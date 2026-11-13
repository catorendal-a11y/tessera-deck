# The pinned Libre Hardware Monitor release and its settings, shared by setup_sensors.ps1 and enable_sensors.ps1.
# Dot-source it: . (Join-Path $PSScriptRoot 'lhm_release.ps1')

$LhmVersion = 'v0.9.6'
$LhmUrl = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/$LhmVersion/LibreHardwareMonitor.zip"
$LhmSha256 = '086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001'
$LhmPort = 8085

# Downloads the release into $Zip and checks its SHA-256. On a mismatch the file is deleted and nothing is extracted.
function Save-LhmZip([string]$Zip) {
    Write-Host "Downloading Libre Hardware Monitor $LhmVersion ..."
    Invoke-WebRequest -Uri $LhmUrl -OutFile $Zip -UseBasicParsing
    $Actual = (Get-FileHash -Path $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $LhmSha256) {
        Remove-Item -Force $Zip
        throw "SHA-256 mismatch. Expected $LhmSha256 but got $Actual. Nothing was installed."
    }
    Write-Host "SHA-256 verified: $Actual"
}

# Turns on the web server Tessera reads (data.json) and starts minimized to the tray. Libre Hardware Monitor listens
# on every network interface, not only 127.0.0.1, so enable_sensors.ps1 adds a firewall rule that blocks the port
# from the network. Tessera itself only reads it over loopback, which Windows Firewall does not filter.
function Write-LhmConfig([string]$Dir) {
    $Settings = [ordered]@{
        runWebServerMenuItem = 'true'
        listenerPort         = "$LhmPort"
        startMinMenuItem     = 'true'
        minTrayMenuItem      = 'true'
        minCloseMenuItem     = 'true'
    }
    $Lines = @('<?xml version="1.0" encoding="utf-8"?>', '<configuration>', '  <appSettings>')
    foreach ($Name in $Settings.Keys) { $Lines += "    <add key=`"$Name`" value=`"$($Settings[$Name])`" />" }
    $Lines += @('  </appSettings>', '</configuration>')
    $Config = Join-Path $Dir 'LibreHardwareMonitor.config'
    [System.IO.File]::WriteAllLines($Config, $Lines, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Configured: $Config"
}
