"""Checks on the sensor install scripts and the workflows that build, audit and publish releases."""
from pathlib import Path
import re
import shutil
import os
import subprocess
import sys
import unittest

from platform_marks import windows_only

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ('tools/lhm_release.ps1', 'tools/setup_sensors.ps1', 'tools/enable_sensors.ps1')

# Runs the elevated part of enable_sensors.ps1 (its last try block) with the scheduled task, process and console
# cmdlets replaced by functions that print what was asked. Libre Hardware Monitor's exe requires administrator, so a
# task for an account without an administrator token never starts it; Start-ScheduledTask models that with STARTS.
ELEVATED_PART = r'''
$ErrorActionPreference = 'Stop'
$global:Started = [bool]$env:RUNNING
function Write-Host { param([Parameter(Position = 0)]$Object, $ForegroundColor) "say: $Object" }
function Invoke-WebRequest { param($Uri, [switch]$UseBasicParsing, $TimeoutSec) if (-not $env:ANSWERS) { throw 'Unable to connect' } }
$LhmPort = 8085
function Start-Sleep { param($Seconds) }
function Install-AdminCopy { }
function Add-FirewallBlock { }
function New-ScheduledTaskAction { }
function New-ScheduledTaskTrigger { }
function New-ScheduledTaskSettingsSet { }
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) $UserId }
function Register-ScheduledTask { param($TaskName, $Action, $Trigger, $Principal, $Settings, [switch]$Force) [Console]::Out.WriteLine("task for: $Principal") }
function Start-ScheduledTask { param($TaskName) 'task started'; if ($env:STARTS) { $global:Started = $true } }
function Start-Process { param($FilePath, $WorkingDirectory) "started: $FilePath"; $global:Started = $true }
function Get-Process { param($Name, $ErrorAction) if ($global:Started) { $Name } }
$Me = [Security.Principal.WindowsIdentity]::GetCurrent()
$Remove = $false
$Once = [bool]$env:ONCE
$TaskName = 'Tessera Sensors'
$InstallDir = 'C:\LHM'
$Exe = 'C:\LHM\LibreHardwareMonitor.exe'
$UserSid = $Me.User.Value
# On a standard account the elevated copy runs as the administrator who typed their password at the prompt.
$Identity = if ($env:STANDARD) { [pscustomobject]@{ User = [pscustomobject]@{ Value = 'S-1-5-32-544' } } } else { $Me }
$Ast = [System.Management.Automation.Language.Parser]::ParseFile($env:SCRIPT, [ref]$null, [ref]$null)
$Main = $Ast.EndBlock.Statements | Where-Object { $_ -is [System.Management.Automation.Language.TryStatementAst] }
. ([scriptblock]::Create($Main.Extent.Text))
'''


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def run_elevated_part(standard, once=False, starts=True, running=False, answers=False):
    env = dict(os.environ, SCRIPT=str(ROOT / 'tools/enable_sensors.ps1'), STANDARD='1' if standard else '',
               ONCE='1' if once else '', STARTS='1' if starts else '', RUNNING='1' if running else '',
               ANSWERS='1' if answers else '')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', ELEVATED_PART],
                            capture_output=True, text=True, timeout=60, env=env)
    return result.stdout + result.stderr


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

    @windows_only
    def test_a_standard_account_gets_it_started_now_and_told_why_not_at_sign_in(self):
        # A standard user has no administrator token, so a sign-in task for them fails every time with "requires
        # elevation". The elevated copy starts it once instead and says what to do.
        for once in (False, True):
            output = run_elevated_part(standard=True, once=once, starts=False)
            self.assertNotIn('task for:', output)
            self.assertIn('started: C:\\LHM\\LibreHardwareMonitor.exe', output)
            self.assertIn('Windows cannot start it at sign-in without a prompt on a standard account', output)
            self.assertNotIn('starts it at every sign-in', output)
            self.assertNotIn('Could not finish', output)

    @windows_only
    def test_an_administrator_account_gets_the_sign_in_task(self):
        output = run_elevated_part(standard=False)
        self.assertRegex(output, r'task for: \S+\\')
        self.assertIn('task started', output)
        self.assertIn('Done. Libre Hardware Monitor starts at every sign-in and is running now.', output)

    @windows_only
    def test_a_copy_that_already_runs_but_cannot_be_read_says_what_to_switch_on(self):
        # Often the user's own copy, with its web server off, a password or another interface (issue 47).
        output = run_elevated_part(standard=False, running=True)
        self.assertNotIn('task started', output)
        self.assertIn('Options > Remote Web Server > Run', output)
        self.assertIn('0.0.0.0', output)
        self.assertNotIn('The temperatures appear', output)
        self.assertNotIn('Could not finish', output)
        answered = run_elevated_part(standard=False, running=True, answers=True)
        self.assertIn('The temperatures appear on the status screen', answered)
        self.assertNotIn('Remote Web Server', answered)


class WorkflowTests(unittest.TestCase):
    def test_every_action_is_pinned_to_a_commit(self):
        """A tag can be moved to other code; a commit SHA cannot. Dependabot keeps the SHA and the version comment current."""
        for path in sorted((ROOT / '.github/workflows').glob('*.yml')):
            for line in path.read_text(encoding='utf-8').splitlines():
                found = re.search(r'uses:\s*([^\s#]+)', line)
                if found and not found.group(1).startswith(('./', 'docker://')):
                    self.assertRegex(found.group(1), r'@[0-9a-f]{40}$', f'{path.name}: {line.strip()}')
                    self.assertRegex(line, r'#\s*v\d', f'{path.name}: say which version the SHA is')

    def test_release_checkouts_do_not_leave_the_token_in_git_config(self):
        release = read('.github/workflows/release.yml')
        checkouts = re.findall(r'- uses: actions/checkout@\S+[^\n]*\n((?: {8,}\S[^\n]*\n)*)', release)
        self.assertEqual(len(checkouts), 4)
        for block in checkouts:
            self.assertIn('persist-credentials: false', block)

    def test_the_lock_file_is_audited_every_week(self):
        audit = read('.github/workflows/audit.yml')
        self.assertRegex(audit, r"schedule:\s+- cron: '[^']+'")
        self.assertIn('python -m pip_audit --require-hashes -r host/requirements.lock', audit)
        self.assertRegex(audit, r'(?m)^permissions:\n  contents: read$')

    def test_the_linux_half_of_the_lock_is_audited_and_installed(self):
        """Tessera.sh installs the lock with hashes; the Windows-only jobs skip the keyring and secretstorage blocks."""
        audit = read('.github/workflows/audit.yml')
        self.assertRegex(audit, r'runs-on: \$\{\{ matrix\.os \}\}')
        self.assertRegex(audit, r'os: \[[^\]]*windows-latest[^\]]*\]')
        self.assertRegex(audit, r'os: \[[^\]]*ubuntu-latest[^\]]*\]')
        job = re.search(r'(?m)^  host-lock-linux:\n((?:    .*\n|\n)+)', read('.github/workflows/ci.yml'))
        self.assertIsNotNone(job, 'ci.yml has no job that installs the lock on Linux')
        self.assertIn('runs-on: ubuntu-latest', job.group(1))
        self.assertIn('pip install --require-hashes -r host/requirements.lock', job.group(1))

    def test_the_linux_lock_job_imports_what_the_first_start_checks_for(self):
        # pip installs a lock that lacks keyring without a word; the first start then finds it missing.
        job = re.search(r'(?m)^  host-lock-linux:\n((?:    .*\n|\n)+)', read('.github/workflows/ci.yml')).group(1)
        probe = re.search(r'xvfb-run -a "\$RUNNER_TEMP/venv/bin/python" -c "([^"]+)"', job)
        self.assertIsNotNone(probe, 'host-lock-linux does not import the packages the first start checks for')
        self.assertLess(job.index('pip install --require-hashes -r host/requirements.lock'), probe.start())
        self.assertIn('MODULE_PROBE', probe.group(1))
        # Without site-packages the step must stop on a missing import, as the first start would. setup_tool itself
        # has to load with the standard library only, or the step fails before the probe runs and proves nothing.
        def run(code):
            return subprocess.run([sys.executable, '-S', '-c', code], cwd=ROOT, capture_output=True, text=True,
                                  timeout=60)
        loaded = run(probe.group(1).replace('exec(MODULE_PROBE)', 'print(MODULE_PROBE)'))
        self.assertEqual(loaded.returncode, 0, f'setup_tool needs more than the standard library:\n{loaded.stderr}')
        result = run(probe.group(1))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No module named', result.stderr)

    def test_the_smoke_test_installs_the_hashed_lock(self):
        smoke = read('.github/workflows/editor-smoke.yml')
        self.assertIn('pip install --require-hashes -r host/requirements.lock', smoke)
        self.assertNotIn('-r host/requirements.txt', smoke)

    def test_a_failed_test_run_fails_the_main_host_job(self):
        # The run block is PowerShell: only the last command sets the result, so coverage report would hide a red run.
        ci = read('.github/workflows/ci.yml')
        self.assertRegex(ci, r'-m unittest discover -s tests -v\n\s+if \(\$LASTEXITCODE\) \{ exit 1 \}')

    def test_the_release_waits_for_the_ci_checks(self):
        self.assertIn('workflow_call:', read('.github/workflows/ci.yml'))
        release = read('.github/workflows/release.yml')
        self.assertRegex(release, r'(?m)^  ci:\n    name: [^\n]+\n    uses: \./\.github/workflows/ci\.yml$')
        self.assertRegex(release, r'needs: \[[^\]]*\bci\b[^\]]*\]')

    def test_a_dry_run_of_the_release_publishes_nothing(self):
        release = read('.github/workflows/release.yml')
        self.assertIn('workflow_dispatch:', release)
        self.assertRegex(release, r"(?m)^  publish:\n    name: [^\n]+\n    if: github\.ref_type == 'tag'")
        self.assertNotIn('idf.py', release, 'the firmware comes from the CI jobs; building it again took 25 minutes')

    def test_the_lock_file_follows_requirements_txt(self):
        """Dependabot edits only requirements.txt; a stale lock would ship the old version in the release zip."""
        def parts(version):
            return tuple(int(n) for n in re.findall(r'\d+', version))

        def key(name):
            return re.sub(r'[-_.]+', '-', name).lower()

        lock = {key(m.group(1)): m.group(2) for m in
                re.finditer(r'(?m)^([A-Za-z0-9._-]+)==([\w.]+)', read('host/requirements.lock'))}
        for line in read('host/requirements.txt').splitlines():
            found = re.match(r'([A-Za-z0-9._-]+)\s*([^;\s]*)', line)
            if not found:
                continue
            name, spec = key(found.group(1)), found.group(2)
            self.assertIn(name, lock, f'{name} is in requirements.txt but not in the lock: run pip-compile')
            have = parts(lock[name])
            for op, version in re.findall(r'(==|>=|<)(\d[\w.]*)', spec):
                ok = {'==': have == parts(version), '>=': have >= parts(version), '<': have < parts(version)}[op]
                self.assertTrue(ok, f'{name}: the lock pins {lock[name]}, requirements.txt wants {op}{version}: run pip-compile')

if __name__ == '__main__':
    unittest.main()
