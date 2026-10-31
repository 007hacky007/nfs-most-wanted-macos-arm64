"""The README's game copy numbers are the ones computed from tools/game_checksums.json."""
from pathlib import Path
import unittest

from tools.game_sources import accepted_copies

ROOT = Path(__file__).resolve().parents[1]


class ReadmeChecksumTests(unittest.TestCase):
    def test_readme_numbers_equal_profile(self):
        readme = ROOT.joinpath('README.md').read_text()
        accepted = accepted_copies()
        folder = accepted['folder']
        text = ' '.join(readme.split())
        for phrase in (f'{folder["required_files"]:,} required files', f'{folder["total_original"]:,} bytes',
                       f'{folder["total_official"]:,} bytes', f'{accepted["discs_total"]:,} bytes'):
            self.assertTrue(phrase in text, phrase)
        lines = readme.splitlines()
        for row in accepted['discs'] + folder['executables']:
            with self.subTest(row=row.get('archive', row.get('kind'))):
                self.assertTrue(any(f'| {row["size"]} |' in line and f'`{row["sha256"]}`' in line for line in lines))


if __name__ == '__main__':
    unittest.main()
