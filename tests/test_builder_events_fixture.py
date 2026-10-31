"""Real builder_cli output, kept as a fixture that the Swift parser tests read.

builder/Tests/BuilderCoreTests/Fixtures/builder-events.txt holds the event lines that
tools/builder_cli.py prints for accepted-copies, a downloads status and a rejected game
copy. This test regenerates them and fails when the file is stale; run it with
NFSMW_UPDATE_FIXTURES=1 to rewrite the file, then run swift test.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import tempfile
import unittest

from tools import builder_cli

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'builder/Tests/BuilderCoreTests/Fixtures/builder-events.txt'


def event_lines(*argv):
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(io.StringIO()):
        builder_cli.main(list(argv))
    return [line for line in output.getvalue().splitlines() if line.startswith('NFSMW-EVENT ')]


class BuilderEventsFixtureTests(unittest.TestCase):
    def generate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            cache = root / 'cache'
            cache.mkdir()
            (cache / '.MW_HQ_1.20.9.zip.partial').write_bytes(b'12345')
            game = root / 'game'
            game.mkdir()
            (game / 'speed.exe').write_bytes(b'not the game')
            lines = (event_lines('accepted-copies')
                     + event_lines('downloads', 'status', '--cache-dir', str(cache), '--helpers')
                     + event_lines('check-game', str(game)))
            text = '\n'.join(lines) + '\n'
            self.assertNotIn(str(root), text)
            return text

    def test_fixture_matches_builder_cli_output(self):
        text = self.generate()
        self.assertEqual(len(text.splitlines()), 3)
        if os.environ.get('NFSMW_UPDATE_FIXTURES') == '1':
            FIXTURE.parent.mkdir(parents=True, exist_ok=True)
            FIXTURE.write_text(text)
        self.assertEqual(FIXTURE.read_text() if FIXTURE.exists() else '', text,
                         'builder-events.txt is stale; run with NFSMW_UPDATE_FIXTURES=1')


if __name__ == '__main__':
    unittest.main()
