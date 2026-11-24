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

    def test_the_aur_wrapper_gives_the_same_gnome_extension_steps_as_tessera_sh(self):
        # packaging/aur/tessera-deck.sh copies the GNOME version warning and the steps after it from Tessera.sh
        def steps(path):
            text = read(path)
            start = text.index('shell_major=')
            end = text.index('\n', text.index('gnome-extensions disable', start))
            # The AUR copy ends that last line with the ;; of its case branch.
            return [line.strip().removesuffix(' ;;') for line in text[start:end].splitlines()]
        self.assertEqual(steps('packaging/aur/tessera-deck.sh'), steps('Tessera.sh'))

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


if __name__ == '__main__':
    unittest.main()
