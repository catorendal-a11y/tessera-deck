#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ini = 'C:\Program Files\HWiNFO64\HWiNFO64.INI'
$exe = 'C:\Program Files\HWiNFO64\HWiNFO64.EXE'

# Read first: a missing INI must fail before HWiNFO is stopped.
$lines = [System.Collections.Generic.List[string]](Get-Content -LiteralPath $ini)
Get-Process HWiNFO64 -ErrorAction SilentlyContinue | Stop-Process -Force
$settings = [ordered]@{
    SensorsOnly = '1'
    MinimalizeSensors = '1'
    OpenSensors = '1'
    SensorsSM = '1'
}
foreach ($name in $settings.Keys) {
    $index = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^' + [regex]::Escape($name) + '=')) {
            $index = $i
            break
        }
    }
    $value = "$name=$($settings[$name])"
    if ($index -ge 0) { $lines[$index] = $value } else { $lines.Add($value) }
}
[System.IO.File]::WriteAllLines($ini, $lines, [System.Text.UTF8Encoding]::new($false))
Start-Process -FilePath $exe
