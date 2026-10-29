import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.runtime_image import (
    HQ_IMAGE_SHA256, OFFICIAL_IMAGE_SHA256, STANDARD_RUNTIME_SHA256,
    _parse_pe, _repair_resources, build_standard_runtime, resource_hashes,
)

ROOT = Path(__file__).resolve().parents[1]
HQ = ROOT / 'out/hq-extract/normalized/LOGIC/41/speed.exe'
OFFICIAL = ROOT / 'out/installed/speed.exe'
LEGACY = ROOT / 'game/speed.exe'


def synthetic_pe(resource_size):
    names = (b'.text', b'.rdata', b'.data', b'.rsrc', b'        ')
    data = bytearray(0x400)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', data, 0x84, 0x14c, 5)
    struct.pack_into('<H', data, 0x94, 224)
    opt = 0x98
    struct.pack_into('<H', data, opt, 0x10b)
    struct.pack_into('<IIII', data, opt + 16, 0x1000, 0x1000, 0x2000, 0x400000)
    struct.pack_into('<II', data, opt + 32, 0x1000, 0x200)
    struct.pack_into('<II', data, opt + 56, 0x8000, 0x400)
    struct.pack_into('<I', data, opt + 92, 16)
    struct.pack_into('<II', data, opt + 112, 0x4000, resource_size - 16)
    rva, raw = 0x1000, 0x400
    for index, name in enumerate(names):
        size = resource_size if name == b'.rsrc' else 0x200
        section = opt + 224 + index * 40
        data[section:section + 8] = name.ljust(8, b'\0')
        struct.pack_into('<IIII', data, section + 8, size - 16, rva, size, raw)
        struct.pack_into('<I', data, section + 36, 0x42000040 if index == 4 else 0x40000040)
        data += bytes([index + 1]) * size
        raw += size
        rva = (rva + size + 0xfff) & ~0xfff
    struct.pack_into('<I', data, opt + 8, resource_size + 3 * 0x200)
    return bytes(data)


class RuntimeImageTests(unittest.TestCase):
    def test_resource_growth_repositions_tail_and_preserves_code(self):
        hq, official = synthetic_pe(0x200), synthetic_pe(0x1800)
        fixed = _repair_resources(hq, official)
        before, after, original = _parse_pe(hq), _parse_pe(fixed), _parse_pe(official)
        for index in range(3):
            self.assertEqual(after['sections'][index], before['sections'][index])
            section = before['sections'][index]
            start, size = section['raw'], section['raw_size']
            self.assertEqual(fixed[start:start + size], hq[start:start + size])
        self.assertEqual(after['sections'][3]['virtual_size'], original['sections'][3]['virtual_size'])
        self.assertEqual(after['sections'][3]['raw_size'], 0x1800)
        self.assertEqual(after['sections'][4]['rva'], original['sections'][4]['rva'])
        self.assertEqual(after['sections'][4]['raw'], original['sections'][4]['raw'])
        self.assertEqual(fixed[-0x200:], hq[-0x200:])
        self.assertEqual(after['resource'], original['resource'])
        self.assertEqual(after['size_of_image'], after['sections'][4]['rva'] + after['sections'][4]['virtual_size'])
        self.assertEqual(after['entrypoint'], before['entrypoint'])
        self.assertEqual(after['imports'], before['imports'])

    def test_known_input_hashes_are_required_before_output_is_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hq, official, output = root / 'hq.exe', root / 'official.exe', root / 'runtime.exe'
            hq.write_bytes(synthetic_pe(0x200))
            official.write_bytes(synthetic_pe(0x1800))
            with self.assertRaisesRegex(ValueError, 'HQ.*SHA-256'):
                build_standard_runtime(hq, official, output)
            self.assertFalse(output.exists())
            with patch('tools.runtime_image.HQ_IMAGE_SHA256', hashlib.sha256(hq.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError, 'official.*SHA-256'):
                    build_standard_runtime(hq, official, output)
            self.assertFalse(output.exists())

    @unittest.skipUnless(HQ.is_file() and OFFICIAL.is_file() and LEGACY.is_file(), 'private game images unavailable')
    def test_private_images_keep_code_and_all_33_original_resources(self):
        hq, official, legacy = HQ.read_bytes(), OFFICIAL.read_bytes(), LEGACY.read_bytes()
        self.assertEqual(hashlib.sha256(hq).hexdigest(), HQ_IMAGE_SHA256)
        self.assertEqual(hashlib.sha256(official).hexdigest(), OFFICIAL_IMAGE_SHA256)
        self.assertEqual(hashlib.sha256(legacy).hexdigest(),
                         '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c')
        expected_resources = resource_hashes(official)
        self.assertEqual(len(expected_resources), 33)
        self.assertEqual(expected_resources, resource_hashes(legacy))
        original_resource = _parse_pe(official)['sections'][3]
        legacy_resource = _parse_pe(legacy)['sections'][3]
        self.assertEqual(official[original_resource['raw']:original_resource['raw'] + original_resource['raw_size']],
                         legacy[legacy_resource['raw']:legacy_resource['raw'] + legacy_resource['raw_size']])
        self.assertNotEqual(expected_resources, resource_hashes(hq))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'runtime.exe'
            result = build_standard_runtime(HQ, OFFICIAL, output)
            fixed = output.read_bytes()
            self.assertEqual(result['sha256'], STANDARD_RUNTIME_SHA256)
            self.assertEqual(hashlib.sha256(fixed).hexdigest(), STANDARD_RUNTIME_SHA256)
            self.assertEqual(resource_hashes(fixed), expected_resources)
            self.assertEqual(fixed, legacy)
            before, after, original = _parse_pe(hq), _parse_pe(fixed), _parse_pe(official)
            for index in range(3):
                section = before['sections'][index]
                start, size = section['raw'], section['raw_size']
                self.assertEqual(fixed[start:start + size], hq[start:start + size])
                self.assertEqual(fixed[start:start + size], legacy[start:start + size])
            self.assertEqual(after['entrypoint'], before['entrypoint'])
            self.assertEqual(after['imports'], before['imports'])
            self.assertEqual(after['resource'], original['resource'])
            self.assertEqual(after['size_of_image'], 0x678e4e)
            self.assertEqual(after['sections'][4]['rva'], 0x638000)
            self.assertEqual(after['sections'][4]['raw'], 5763072)
            self.assertEqual(build_standard_runtime(HQ, OFFICIAL, output), result)

    def test_malformed_pe_is_rejected(self):
        for data in (b'', b'MZ' + bytes(62), synthetic_pe(0x200)[:200]):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                _parse_pe(data)


if __name__ == '__main__':
    unittest.main()
