from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.target import recover_relocations, check_module_range


def fake_pe(blob):
    section = SimpleNamespace(Name=b'        ', VirtualAddress=0x5000,
                              Misc_VirtualSize=len(blob), get_data=lambda: blob)
    return SimpleNamespace(sections=[section],
                           OPTIONAL_HEADER=SimpleNamespace(ImageBase=0x400000, SizeOfImage=0x10000),
                           get_dword_at_rva=lambda a: 0x401000 if 0x1000 <= a < 0x2000 else None)


class TargetTests(unittest.TestCase):
    def test_whitespace_relocation_section(self):
        blob = struct.pack('<IIHH', 0x1000, 12, 0x3010, 0)
        self.assertEqual(recover_relocations(fake_pe(blob)), [0x401010])

    def test_bad_relocations_fail(self):
        for blob in (struct.pack('<II', 0x1000, 100),
                     struct.pack('<IIHH', 0x1001, 12, 0x3010, 0),
                     struct.pack('<IIHH', 0x1000, 12, 0x5010, 0),
                     struct.pack('<IIHH', 0x3000, 12, 0x3010, 0)):
            with self.assertRaises(ValueError):
                recover_relocations(fake_pe(blob))

    def test_dll_does_not_overlap_game_or_heap(self):
        check_module_range(0x02000000, 0x24a000)
        for base in (0x400000, 0xa00000, 0xc00000, 0x03000000, 0x10000000, 0x7f000000):
            with self.assertRaises(ValueError):
                check_module_range(base, 0x24a000)

    def test_no_donor_specific_return_assumptions(self):
        active = [l.split('#')[0].strip() for l in Path('tools/retpast.txt').read_text().splitlines()]
        self.assertEqual([l for l in active if l], [])

    def test_lifter_excludes_dll_constant_prefix(self):
        from tools.lift import Lifter
        section = SimpleNamespace(Name=b'.text\0\0\0', VirtualAddress=0x1000,
                                  Misc_VirtualSize=100, get_data=lambda: b'\x90' * 100)
        pe = SimpleNamespace(sections=[section], OPTIONAL_HEADER=SimpleNamespace(ImageBase=0x400000))
        with patch('tools.lift.pefile.PE', return_value=pe), patch.dict('os.environ', {'CODE_RVA_START': '0x1020'}):
            lifter = Lifter('unused')
        self.assertFalse(lifter.in_text(0x401000))
        self.assertTrue(lifter.in_text(0x401020))
        self.assertEqual(lifter.TSZ, 68)


if __name__ == '__main__':
    unittest.main()
