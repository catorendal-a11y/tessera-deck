"""Checks that keep the docs, CI and native test stubs in step with the code."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


class RepoHygieneTests(unittest.TestCase):
    def test_native_targets_stub_every_time_service_call_of_the_ui(self):
        # These targets link ui.cpp without time_service.c, so a new call there breaks the default native build.
        called = set(re.findall(r'\b(time_service_\w+)\s*\(', read('main/ui/ui.cpp')))
        self.assertTrue(called)
        for stub in ('tests/native/render_screens.cpp', 'tests/native/test_ui.cpp', 'tests/native/cache_bench.cpp'):
            missing = {name for name in called if not re.search(r'\b' + name + r'\s*\(\s*\)\s*\{', read(stub))}
            self.assertFalse(missing, f'{stub} lacks stubs for {sorted(missing)}')

    def test_the_docs_build_the_v3_chip_image_as_ci_does(self):
        # A default build caps the chip revision at v1.99, so esptool refuses it on a v3.x GUITION board. The docs
        # copy the v3 commands from ci.yml (the release ships what ci.yml built), so a change there must reach them too.
        ci = read('.github/workflows/ci.yml')
        row = re.search(r'\{board: (tessera-p4-v3), target: \S+, defaults: (\S+)\}', ci)
        self.assertIsNotNone(row, 'ci.yml builds no tessera-p4-v3 image')
        built = ci.replace('${{ matrix.board }}', row.group(1)).replace('${{ matrix.defaults }}', row.group(2))
        recipe = ('python3 tools/v3_sdkconfig.py sdkconfig build/tessera-p4-v3/sdkconfig',
                  'idf.py -B build/tessera-p4-v3 -DSDKCONFIG=build/tessera-p4-v3/sdkconfig',
                  f'-DSDKCONFIG_DEFAULTS="sdkconfig.defaults;{row.group(2)}"')
        for part in recipe:
            self.assertIn(part, built, f'ci.yml no longer builds the v3 image with: {part}')
            for doc in ('docs/INSTALL.md', 'docs/DEVELOPMENT.md'):
                self.assertIn(part.replace('python3 ', 'python ', 1), read(doc), f'{doc} lacks the v3 build command from ci.yml')

    def test_the_bug_report_form_asks_linux_users_for_what_triage_needs(self):
        form = read('.github/ISSUE_TEMPLATE/bug_report.yml')
        field = re.search(r'- type: input\s+id: (?:os|windows)\s+attributes:\s+label: (.+)\s+description: (.+)', form)
        self.assertIsNotNone(field)
        self.assertEqual(field.group(1), 'Operating system')
        for word in ('winver', 'distro', 'X11', 'Wayland'):
            self.assertIn(word, field.group(2))
        # The status line shows the firmware version only while a panel is connected.
        self.assertIn('when the panel is connected', form)

    def test_cppcheck_covers_every_firmware_source(self):
        ci = read('.github/workflows/ci.yml')
        sources = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'main').rglob('*')
                   if p.suffix in ('.c', '.cpp') and 'fonts' not in p.parts}
        self.assertTrue(sources)
        self.assertFalse({s for s in sources if s not in ci}, 'add the new firmware source to the cppcheck step')

    def test_contributing_runs_the_same_lint_as_ci(self):
        command = re.search(r'ruff check [^\n]+', read('.github/workflows/ci.yml')).group(0)
        self.assertIn(command, read('CONTRIBUTING.md'))
        self.assertIn(command, read('docs/DEVELOPMENT.md'))

    @unittest.skipUnless(shutil.which('git') and (ROOT / '.git').exists(), 'needs a git checkout')
    def test_gitignore_covers_the_temp_files_of_atomic_writes(self):
        for name in ('host/profiles.json.k3j2.tmp', 'host/deck-runtime.local.tmp'):
            result = subprocess.run(['git', 'check-ignore', '-q', name], cwd=ROOT)
            self.assertEqual(result.returncode, 0, f'{name} is not ignored')

    def test_relative_links_in_the_docs_point_at_files(self):
        pages = [ROOT / name for name in ('README.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'VERIFICATION.md')]
        pages += sorted((ROOT / 'docs').glob('*.md'))
        broken = []
        for page in pages:
            if not page.exists():
                continue
            for target in re.findall(r'\]\(([^)\s]+)\)', page.read_text(encoding='utf-8')):
                if re.match(r'[a-z]+:|#', target):
                    continue
                if not (page.parent / target.split('#')[0]).exists():
                    broken.append(f'{page.relative_to(ROOT).as_posix()}: {target}')
        self.assertEqual(broken, [])

    def test_the_deckctl_examples_use_the_virtual_environments_python(self):
        # deckctl imports psutil, which only the venv has: a plain `python` fails with ModuleNotFoundError
        pages = [*sorted((ROOT / 'docs').glob('*.md')), ROOT / 'docs' / 'index.html']
        bare = [f'{page.name}: {line.strip()}' for page in pages for line in page.read_text(encoding='utf-8').splitlines()
                if re.search(r'(?<![\w\\/.])python\s+host\\deckctl\.py', line)]
        self.assertEqual(bare, [])


if __name__ == '__main__':
    unittest.main()
