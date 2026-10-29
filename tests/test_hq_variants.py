from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.hq_variants import FULL_COPIES, FULL_INI, build_variants, selected_files, verify_runtime, invalidate_preload_caches


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def fixture(root):
    base, source = root / 'game', root / 'hq'
    base.mkdir()
    source.mkdir()
    pe = bytearray(128)
    pe[:2] = b'MZ'
    struct.pack_into('<I', pe, 0x3c, 64)
    pe[64:70] = b'PE\0\0\x4c\x01'
    base_files = {
        'speed.exe': b'original executable', 'GLOBAL/GLOBALB.BUN': b'original car list',
        'GLOBAL/GlobalB.lzc': b'original compressed car list',
        'GLOBAL/attributes.bin': b'original attributes', 'GLOBAL/gameplay.bin': b'original gameplay',
        'GLOBAL/gameplay.lzc': b'original compressed gameplay',
        'GLOBAL/GlobalMemoryFile.bin': struct.pack('<4I',0,0,0x53219999,1) + b'stock cached geometry',
        'GLOBAL/InGameMemoryFile.bin': struct.pack('<4I',0,0,0x53219999,1) + b'stock cached textures',
        'GLOBAL/PermanentMemoryFile.bin': struct.pack('<4I',0,0,0x53219999,1) + b'stock cached headers',
        'CARS/BASE/GEOMETRY.BIN': b'original model', 'TRACKS/L2RA.BUN': b'original world',
        'TRACKS/L2RA.lzc': b'stale compressed world',
        'FX/COMPILED/car.fx.o': b'original SM2 shader',
        'FX/COMPILED/carnormalmap.fx.o': b'original normal map shader',
        'SOUND/PFDATA/MW_Music.mpf': b'original music index',
        'SOUND/PFDATA/MW_Music.mus': b'original music', 'MOVIES/intro.vp6': b'original video',
    }
    for name, data in base_files.items():
        put(base, name, data)
    for original, _ in FULL_COPIES:
        put(source, original, original.encode())
    put(source, 'LOGIC/41/speed.exe', pe)
    for relative, values in FULL_INI.items():
        put(source, relative, ('[Settings]\n' + '\n'.join(f'{key} = 0' for key in values) + '\n').encode())
    extras = {
        'CARS/BASE/GEOMETRY.BIN': b'HQ model', 'CARS/ADDED/GEOMETRY.BIN': b'added car',
        'TRACKS/L2RA.BUN': b'HQ world', 'TEX/ROCKPORT360/textures.bin': b'world textures',
        'LOGIC/41/FX/carnormalmap.fx.o': b'unsupported replacement normal map shader',
        'GLOBAL/GLOBALB.BUN': b'HQ base car list',
        'GLOBAL/GlobalMemoryFile.bin': struct.pack('<4I',0,0,0x53219999,0),
        'GLOBAL/InGameMemoryFile.bin': struct.pack('<4I',0,0,0x53219999,0),
        'GLOBAL/PermanentMemoryFile.bin': struct.pack('<4I',0,0,0x53219999,0),
        'GLOBAL/GLOBALA.BUN#lang-en': b'English', 'GLOBAL/GLOBALA.BUN#lang-ru': b'Russian',
        'SOUND/PFDATA/MW_Music.mpf$0': b'HQ original music index',
        'SOUND/PFDATA/MW_Music.mpf$1': b'alternative music index',
        'SOUND/PFDATA/MW_Music.mus$0': b'HQ original playlist',
        'SOUND/PFDATA/MW_Music.mus$1': b'alternative playlist',
        'SOUND/ENGINE/new.gin': b'HQ engine audio', 'MOVIES/boot.vp6': b'HQ boot video',
    }
    for name, data in extras.items():
        put(source, name, data)
    manifest = {'version': '1.20.9', 'files': {}, 'variants': {
        'GLOBAL/GLOBALA.BUN': ['GLOBAL/GLOBALA.BUN#lang-en', 'GLOBAL/GLOBALA.BUN#lang-ru'],
        'SOUND/PFDATA/MW_Music.mpf': ['SOUND/PFDATA/MW_Music.mpf$0', 'SOUND/PFDATA/MW_Music.mpf$1'],
        'SOUND/PFDATA/MW_Music.mus': ['SOUND/PFDATA/MW_Music.mus$0', 'SOUND/PFDATA/MW_Music.mus$1'],
    }}
    for path in source.rglob('*'):
        if path.is_file():
            manifest['files'][path.relative_to(source).as_posix()] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (source / '.hq-manifest.json').write_text(json.dumps(manifest))
    return base, source, hashlib.sha256(pe).hexdigest(), base_files


@contextmanager
def runtime_patches(hq_hash):
    canonical = bytearray(128)
    canonical[:2] = b'MZ'
    struct.pack_into('<I', canonical, 0x3c, 64)
    canonical[64:70] = b'PE\0\0\x4c\x01'
    canonical[3] = 1
    canonical_hash = hashlib.sha256(canonical).hexdigest()

    def reconstruct(hq, official, output):
        Path(output).write_bytes(canonical)

    with patch('tools.hq_variants.HQ_RUNTIME_SHA256', hq_hash), \
            patch('tools.hq_variants.RUNTIME_SHA256', canonical_hash), \
            patch('tools.hq_variants.build_standard_runtime', side_effect=reconstruct):
        yield canonical_hash


class HQVariantTests(unittest.TestCase):
    def test_separate_visual_and_full_trees_preserve_standard_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, source, runtime_hash, originals = fixture(Path(temporary))
            with runtime_patches(runtime_hash) as standard_hash:
                manifest = build_variants(base, source)
            visual, full = base / '.nfsmw/visuals', base / '.nfsmw/full'
            for name, data in originals.items():
                self.assertEqual((base / name).read_bytes(), data)
            for name in ('GLOBAL/GLOBALB.BUN', 'GLOBAL/GlobalB.lzc', 'GLOBAL/attributes.bin',
                         'GLOBAL/gameplay.bin', 'GLOBAL/gameplay.lzc', 'SOUND/PFDATA/MW_Music.mus',
                         'SOUND/PFDATA/MW_Music.mpf', 'MOVIES/intro.vp6', 'FX/COMPILED/car.fx.o'):
                self.assertEqual((visual / name).read_bytes(), originals[name])
            for cache in ('GlobalMemoryFile.bin','InGameMemoryFile.bin','PermanentMemoryFile.bin'):
                relative='GLOBAL/'+cache
                self.assertEqual((visual/relative).read_bytes(),struct.pack('<4I',0,0,0x53219999,0))
                self.assertEqual(manifest['variants']['visuals']['files'][relative],
                                 hashlib.sha256((visual/relative).read_bytes()).hexdigest())
                self.assertEqual((full/relative).read_bytes(),(source/relative).read_bytes())
            self.assertEqual((visual / 'CARS/BASE/GEOMETRY.BIN').read_bytes(), b'HQ model')
            self.assertFalse((visual / 'CARS/ADDED').exists())
            self.assertFalse((visual / 'TRACKS/L2RA.lzc').exists())
            self.assertEqual((full / 'GLOBAL/GlobalB.lzc').read_bytes(), b'LOGIC/360osd/GlobalB.lzc')
            self.assertEqual((full / 'GLOBAL/InGameA.bun').read_bytes(), b'LOGIC/360osd/InGameA.bun')
            self.assertEqual((full / 'GLOBAL/attributes.bin').read_bytes(), b'LOGIC/360osd/attributes.bin')
            self.assertEqual((full / 'GLOBAL/gameplay.lzc').read_bytes(), b'LOGIC/360osd/gameplay.lzc')
            self.assertEqual((full / 'GLOBAL/GLOBALA.BUN').read_bytes(), b'English')
            self.assertEqual((full / 'SOUND/PFDATA/MW_Music.mus').read_bytes(), b'HQ original playlist')
            self.assertTrue((full / 'CARS/ADDED/GEOMETRY.BIN').is_file())
            self.assertTrue((full / 'MOVIES/boot.vp6').is_file())
            self.assertFalse((full / 'LOGIC').exists())
            self.assertEqual((full / 'FX/COMPILED/carnormalmap.fx.o').read_bytes(), b'original normal map shader')
            self.assertEqual(hashlib.sha256((base / '.nfsmw/runtime.exe').read_bytes()).hexdigest(), standard_hash)
            self.assertEqual(hashlib.sha256((visual / 'speed.exe').read_bytes()).hexdigest(), standard_hash)
            self.assertEqual(hashlib.sha256((full / 'speed.exe').read_bytes()).hexdigest(), runtime_hash)
            self.assertTrue((base / '.nfsmw/variants.json').is_file())
            self.assertTrue(manifest['variants']['visuals']['ready'])
            self.assertEqual(manifest['variants']['visuals']['pending'], [])
            self.assertTrue(manifest['variants']['full']['ready'])
            self.assertEqual(manifest['variants']['full']['pending'], [])
            widescreen = (full / 'scripts/NFSMostWanted.WidescreenFix.ini').read_text()
            self.assertIn('ShadowsRes = 4096', widescreen)
            self.assertIn('SkipIntro = 0', widescreen)
            self.assertIn('UseFullLODShaderOnTrafficAndCops = 1', (full / 'scripts/X360Stuff.ini').read_text())

    def test_preload_cache_rejects_unknown_header_without_changing_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            put(root,'GLOBAL/GlobalMemoryFile.bin',b'unknown cache format')
            with self.assertRaisesRegex(ValueError,'unsupported preload cache'):
                invalidate_preload_caches(root)
            self.assertEqual((root/'GLOBAL/GlobalMemoryFile.bin').read_bytes(),b'unknown cache format')

    @unittest.skipUnless(Path('out/installed/.nfsmw/visuals/CARS/WHEELS/GEOMETRY.BIN').is_file(),
                         'requires local stock and HQ wheel assets')
    def test_stock_preload_offsets_reproduce_visual8_corrupt_payloads(self):
        stock=Path('out/installed/CARS/WHEELS/GEOMETRY.BIN').read_bytes()
        replacement=Path('out/installed/.nfsmw/visuals/CARS/WHEELS/GEOMETRY.BIN').read_bytes()
        cache=Path('out/installed/GLOBAL/GlobalMemoryFile.bin').read_bytes()
        count=struct.unpack_from('<I',cache,12)[0]
        descriptor=next(struct.unpack_from('<5I',cache,16+i*20) for i in range(count)
                        if struct.unpack_from('<I',cache,16+i*20)[0]==0x5979c67b)
        _,offset,file_bytes,cached_bytes,_=descriptor
        self.assertEqual(file_bytes,len(stock))
        prefix=cache[offset:offset+cached_bytes]
        self.assertEqual(prefix,stock[:cached_bytes])
        # Exact garbage tags observed in the failing original loader, using
        # stock offsets against the selected HQ file. The final case is EOF.
        cases=((0x9d6ef115,0xc49900,0xbcfb9a5c),
               (0x9d6ef116,0xc52a80,0x3e8472fb),
               (0x9d6ef117,0xc57400,0x3d200000),
               (0xcff9b09c,0x103a780,None))
        for key,source_offset,garbage in cases:
            position=prefix.find(struct.pack('<II',key,source_offset))
            self.assertGreaterEqual(position,0)
            if garbage is None:
                self.assertGreater(source_offset,len(replacement))
            else:
                self.assertEqual(struct.unpack_from('<I',replacement,source_offset)[0],garbage)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);put(root,'GLOBAL/GlobalMemoryFile.bin',cache)
            invalidate_preload_caches(root)
            self.assertEqual((root/'GLOBAL/GlobalMemoryFile.bin').read_bytes(),
                             struct.pack('<4I',0,0,0x53219999,0))

    def test_corrupt_source_fails_before_publishing_variants(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, source, runtime_hash, _ = fixture(Path(temporary))
            (source / 'CARS/BASE/GEOMETRY.BIN').write_bytes(b'corrupted')
            with runtime_patches(runtime_hash), self.assertRaisesRegex(ValueError, 'hash mismatch'):
                build_variants(base, source)
            self.assertFalse((base / '.nfsmw/visuals').exists())
            self.assertFalse((base / '.nfsmw/full').exists())
            self.assertFalse((base / '.nfsmw/runtime.exe').exists())

    def test_base_symlink_is_not_followed_into_the_variant(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, source, runtime_hash, _ = fixture(Path(temporary))
            (base / 'outside').symlink_to('/etc')
            with runtime_patches(runtime_hash), self.assertRaisesRegex(ValueError, 'symlinks'):
                build_variants(base, source)
            self.assertFalse((base / '.nfsmw/full').exists())

    def test_managed_directory_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base, source, runtime_hash, _ = fixture(root)
            outside = root / 'outside'
            outside.mkdir()
            (base / '.nfsmw').symlink_to(outside)
            with runtime_patches(runtime_hash), self.assertRaisesRegex(ValueError, 'symlink'):
                build_variants(base, source)
            self.assertEqual(list(outside.iterdir()), [])

    def test_existing_variant_is_kept(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, source, runtime_hash, _ = fixture(Path(temporary))
            sentinel = base / '.nfsmw/visuals/sentinel'
            sentinel.parent.mkdir(parents=True)
            sentinel.write_bytes(b'keep')
            with runtime_patches(runtime_hash), self.assertRaises(FileExistsError):
                build_variants(base, source)
            self.assertEqual(sentinel.read_bytes(), b'keep')

    def test_runtime_rejects_wrong_hash_or_architecture(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, source, _, _ = fixture(Path(temporary))
            runtime = source / 'LOGIC/41/speed.exe'
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                verify_runtime(runtime)
            data = bytearray(runtime.read_bytes())
            data[68:70] = b'\x64\x86'
            runtime.write_bytes(data)
            with patch('tools.hq_variants.HQ_RUNTIME_SHA256', hashlib.sha256(data).hexdigest()), self.assertRaisesRegex(ValueError, 'i386'):
                verify_runtime(runtime)

    def test_unknown_variant_needs_explicit_selection(self):
        with self.assertRaisesRegex(ValueError, 'no explicit default'):
            selected_files({'files': {}, 'variants': {'unknown.bin': ['unknown.bin$0', 'unknown.bin$1']}})


if __name__ == '__main__':
    unittest.main()
