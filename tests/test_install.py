import hashlib
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from tools.install_game import RawISO, disc_files, extract_zip, install, verify_binary


def raw_image(path, logical):
    logical += b'\0' * (-len(logical) % 2048)
    out = bytearray()
    for i in range(0, len(logical), 2048):
        out += b'\0' + b'\xff' * 10 + b'\0' + b'\0\0\0\x01'
        out += logical[i:i + 2048] + bytes(288)
    path.write_bytes(out)


def record(name, sector, size, directory=False):
    n = 33 + len(name)
    n += n % 2
    r = bytearray(n)
    r[0] = n
    struct.pack_into('<I', r, 2, sector)
    struct.pack_into('>I', r, 6, sector)
    struct.pack_into('<I', r, 10, size)
    struct.pack_into('>I', r, 14, size)
    r[25] = 2 if directory else 0
    r[28:32] = b'\x01\0\0\x01'
    r[32] = len(name)
    r[33:33 + len(name)] = name
    return r


class InstallTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('NFSMW_ISO_BACKUP'), 'set NFSMW_ISO_BACKUP for the local ISO installation test')
    def test_iso_install_applies_official_patch_and_retains_native_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'game'
            manifest = install(Path(os.environ['NFSMW_ISO_BACKUP']), root,
                               hq_source=os.environ.get('NFSMW_HQ_SOURCE'))
            self.assertEqual(len(manifest['archives']), 4)
            self.assertEqual(len(manifest['patches']['official-1.3']), 7)
            self.assertEqual(hashlib.sha256((root / 'speed.exe').read_bytes()).hexdigest(),
                             'e8019e0d7b706beba5ec648a50108a9a13346695eba9ebe58b6d796260d3c4eb')
            self.assertTrue((root / 'scripts/NFSMostWanted.WidescreenFix.ini').is_file())
            self.assertEqual(hashlib.sha256((root / '.nfsmw/runtime.exe').read_bytes()).hexdigest(),
                             '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c')
            self.assertEqual(set(manifest['variants']), {'visuals', 'full'})
            self.assertTrue(manifest['variants']['full']['ready'])

    def test_plain_iso_cross_sector_reads_and_bounded_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'disc.iso'
            data = bytearray(bytes(range(256)) * 160)
            data[16 * 2048:16 * 2048 + 7] = b'\x01CD001\x01'
            p.write_bytes(data)
            with RawISO(p) as f:
                self.assertEqual(f.read(2051), data[:2051])
                f.seek(-12, 2)
                self.assertEqual(f.read(), data[-12:])
            with RawISO(p, base=2040, size=25) as f:
                self.assertEqual(f.read(100), data[2040:2065])
                self.assertEqual(f.read(), b'')
            with self.assertRaises(ValueError):
                RawISO(p, base=len(data) - 1, size=2)
            p.write_bytes(data[:-1])
            with self.assertRaises(ValueError):
                RawISO(p)

    def test_cross_sector_reads_and_bounded_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'disc.bin'
            data = bytes(range(256)) * 32
            raw_image(p, data)
            with RawISO(p) as f:
                self.assertEqual(f.read(2051), data[:2051])
                f.seek(-12, 2)
                self.assertEqual(f.read(), data[-12:])
            with RawISO(p, base=2040, size=25) as f:
                self.assertEqual(f.read(100), data[2040:2065])
                self.assertEqual(f.read(), b'')

    def test_truncated_and_wrong_sector_mode_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'disc.bin'
            p.write_bytes(bytes(2351))
            with self.assertRaises(ValueError):
                RawISO(p)
            p.write_bytes(bytes(2352))
            with self.assertRaises(ValueError):
                RawISO(p)

    def test_joliet_preserves_long_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'disc.bin'
            data = bytearray(24 * 2048)
            for sector, kind in ((16, 1), (17, 2), (18, 255)):
                at = sector * 2048
                data[at:at + 7] = bytes([kind]) + b'CD001\x01'
            data[17 * 2048 + 88:17 * 2048 + 91] = b'%/E'
            r = record(b'\0', 20, 2048, True)
            data[17 * 2048 + 156:17 * 2048 + 156 + len(r)] = r
            name = '0compressed.zip;1'.encode('utf-16-be')
            r = record(name, 22, 17)
            data[20 * 2048:20 * 2048 + len(r)] = r
            raw_image(p, data)
            found = disc_files(p)
            self.assertEqual([(f.name, f.offset, f.size) for f in found],
                             [('0compressed.zip', 22 * 2048, 17)])
            p = Path(tmp) / 'disc.iso'
            p.write_bytes(data)
            self.assertEqual(disc_files(p), found)

    def test_zip_paths_and_symlinks_cannot_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'game'
            root.mkdir()
            for name in ('../outside', '/outside', 'C:\\outside', '..\\outside'):
                b = io.BytesIO()
                with zipfile.ZipFile(b, 'w') as z:
                    z.writestr(name, b'bad')
                b.seek(0)
                with zipfile.ZipFile(b) as z, self.assertRaises(ValueError):
                    extract_zip(z, root)
            (root / 'LINK').symlink_to(Path(tmp), target_is_directory=True)
            b = io.BytesIO()
            with zipfile.ZipFile(b, 'w') as z:
                z.writestr('LINK/outside', b'bad')
            b.seek(0)
            with zipfile.ZipFile(b) as z, self.assertRaises(ValueError):
                extract_zip(z, root)
            self.assertFalse((Path(tmp) / 'outside').exists())

    def test_crc_is_checked_and_windows_paths_are_decoded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = io.BytesIO()
            with zipfile.ZipFile(b, 'w') as z:
                z.writestr('GLOBAL\\test.bin', b'abc')
            b.seek(0)
            with zipfile.ZipFile(b) as z:
                self.assertEqual(extract_zip(z, root), 1)
            self.assertEqual((root / 'GLOBAL' / 'test.bin').read_bytes(), b'abc')
            raw = bytearray(b.getvalue())
            raw[30 + len('GLOBAL\\test.bin')] ^= 1
            with zipfile.ZipFile(io.BytesIO(raw)) as z, self.assertRaises(zipfile.BadZipFile):
                extract_zip(z, root)

    def test_wrong_hash_and_x64_are_rejected(self):
        data = bytearray(128)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 0x3c, 64)
        data[64:68] = b'PE\0\0'
        struct.pack_into('<H', data, 68, 0x8664)
        with self.assertRaises(ValueError):
            verify_binary(bytes(data), hashlib.sha256(data).hexdigest())
        struct.pack_into('<H', data, 68, 0x14c)
        with self.assertRaises(ValueError):
            verify_binary(bytes(data), '0' * 64)
        verify_binary(bytes(data), hashlib.sha256(data).hexdigest())

    def test_existing_install_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'game'
            root.mkdir()
            (root / 'save').write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                install(Path(tmp) / 'missing', root)
            with self.assertRaises(FileExistsError):
                install([Path(tmp)/'missing.iso'],root,patches={})
            self.assertEqual((root / 'save').read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
