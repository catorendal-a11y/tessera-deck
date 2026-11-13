"""Checks on the sensor install scripts and the workflows that build, audit and publish releases."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ('tools/lhm_release.ps1', 'tools/setup_sensors.ps1', 'tools/enable_sensors.ps1')


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


class SensorScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('powershell.exe'), 'needs Windows PowerShell')
    def test_scripts_parse(self):
        for script in SCRIPTS:
            command = ('$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('
                       f"'{ROOT / script}', [ref]$null, [ref]$e); if ($e) {{ $e | ForEach-Object Message; exit 1 }}")
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, f'{script}: {result.stdout}{result.stderr}')

    def test_the_logon_task_runs_a_copy_only_administrators_can_change(self):
        # The Tessera folder is writable by every program the user runs: an elevated task started from there runs
        # whatever was swapped in as administrator, without a prompt.
        script = read('tools/enable_sensors.ps1')
        self.assertRegex(script, r"\$Base = Join-Path \$env:ProgramFiles 'Tessera'")
        self.assertRegex(script, r"\$InstallDir = Join-Path \$Base ")
        self.assertNotIn('Split-Path -Parent $PSScriptRoot', script)
        self.assertIn('New-ScheduledTaskAction -Execute $Exe', script)
        self.assertRegex(script, r"icacls\.exe \$Dir /inheritance:r /grant:r '\*S-1-5-32-544:\(OI\)\(CI\)F' "
                                 r"'\*S-1-5-18:\(OI\)\(CI\)F' '\*S-1-5-32-545:\(OI\)\(CI\)RX'")
        install = script[script.index('function Install-AdminCopy'):]
        # Locked before anything is downloaded, and downloaded inside the locked folder, not the user's TEMP.
        self.assertLess(install.index('Protect-AdminOnly $Base'), install.index('Save-LhmZip'))
        self.assertIn("$Stage = Join-Path $Base", install)
        self.assertNotIn('GetTempPath', script)
        self.assertLess(script.index('Install-AdminCopy\n    Add-FirewallBlock'), script.index('Register-ScheduledTask'))

    def test_the_zip_is_checked_before_it_is_extracted(self):
        helper = read('tools/lhm_release.ps1')
        body = helper[helper.index('function Save-LhmZip'):helper.index('function Write-LhmConfig')]
        self.assertIn('Get-FileHash -Path $Zip -Algorithm SHA256', body)
        self.assertRegex(body, r'if \(\$Actual -ne \$LhmSha256\) \{\s+Remove-Item -Force \$Zip\s+throw')
        self.assertRegex(helper, r"\$LhmSha256 = '[0-9a-f]{64}'")
        for script in ('tools/setup_sensors.ps1', 'tools/enable_sensors.ps1'):
            text = read(script)
            self.assertLess(text.index('Save-LhmZip $Zip'), text.index('Expand-Archive'), script)

    def test_setup_never_starts_the_writable_copy_elevated(self):
        script = read('tools/setup_sensors.ps1')
        self.assertNotRegex(script, r'(?m)^[^#\n]*-Verb RunAs')
        self.assertIn("& (Join-Path $PSScriptRoot 'enable_sensors.ps1') -Once", script)
        # A fresh directory, not -Force over the old one: files planted there before would stay beside the new ones.
        self.assertNotRegex(script, r'Expand-Archive[^\n]*-Force')
        self.assertNotRegex(read('tools/enable_sensors.ps1'), r'Expand-Archive[^\n]*-Force')

    def test_the_sensor_port_is_blocked_from_the_network(self):
        # Libre Hardware Monitor listens on every interface; only loopback (unfiltered) should reach it.
        script = read('tools/enable_sensors.ps1')
        self.assertRegex(script, r'New-NetFirewallRule -Name \$FirewallRule [^\n]*`\s+-Direction Inbound -Action Block '
                                 r'-Protocol TCP -LocalPort \$LhmPort -Profile Any')
        self.assertIn('Remove-NetFirewallRule -Name $FirewallRule', script)
        self.assertIn("listenerPort         = \"$LhmPort\"", read('tools/lhm_release.ps1'))
        self.assertNotIn('loopback only', read('tools/lhm_release.ps1') + read('tools/setup_sensors.ps1'))


class WorkflowTests(unittest.TestCase):
    def test_release_checkouts_do_not_leave_the_token_in_git_config(self):
        release = read('.github/workflows/release.yml')
        checkouts = re.findall(r'- uses: actions/checkout@\S+\n((?: {8,}\S[^\n]*\n)*)', release)
        self.assertEqual(len(checkouts), 3)
        for block in checkouts:
            self.assertIn('persist-credentials: false', block)

    def test_the_lock_file_is_audited_every_week(self):
        audit = read('.github/workflows/audit.yml')
        self.assertRegex(audit, r"schedule:\s+- cron: '[^']+'")
        self.assertIn('python -m pip_audit --require-hashes -r host/requirements.lock', audit)
        self.assertRegex(audit, r'(?m)^permissions:\n  contents: read$')

    def test_the_smoke_test_installs_the_hashed_lock(self):
        smoke = read('.github/workflows/editor-smoke.yml')
        self.assertIn('pip install --require-hashes -r host/requirements.lock', smoke)
        self.assertNotIn('-r host/requirements.txt', smoke)


if __name__ == '__main__':
    unittest.main()
