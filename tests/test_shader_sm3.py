"""Native shader, COM and Metal checks, using supplied HQ files when available."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT


def standard_pixels():
    from tools.runtime_image import _parse_pe, STANDARD_RUNTIME_SHA256
    import hashlib
    image = (REPO / 'out/installed/.nfsmw/runtime.exe').read_bytes()
    assert hashlib.sha256(image).hexdigest() == STANDARD_RUNTIME_SHA256
    section = next(s for s in _parse_pe(image)['sections'] if s['name'] == b'.rsrc')
    data = image[section['raw']:section['raw'] + section['raw_size']]
    shaders = []
    for offset in range(0, len(data) - 4, 4):
        version = struct.unpack_from('<I', data, offset)[0]
        if version not in (0xffff0101,0xffff0102,0xffff0103,0xffff0104,0xffff0200):
            continue
        cursor = offset + 4
        while cursor + 4 <= min(offset + 65536, len(data)):
            token = struct.unpack_from('<I', data, cursor)[0]
            opcode = token & 0xffff
            if opcode == 0xffff:
                shaders.append((offset, data[offset:cursor + 4]))
                break
            if opcode == 0xfffe:
                cursor += 4 * (1 + ((token >> 16) & 0x7fff))
            elif opcode == 81:
                cursor += 24
            elif opcode <= 97 or opcode == 0xfffd:
                if version >= 0xffff0200:
                    cursor += 4 * (1 + ((token >> 24) & 15))
                else:
                    cursor += 4
                    while cursor + 4 <= len(data) and struct.unpack_from('<I', data, cursor)[0] & 0x80000000:
                        cursor += 4
            else:
                break
    return shaders


@unittest.skipUnless(sys.platform == 'darwin', 'Native Metal tests require macOS')
class ShaderSM3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        cls.binary = cls.directory / 'shader-sm3'
        cls.backend = cls.directory / 'backend-sm3'
        cls.com = cls.directory / 'com-sm3'
        include = ['-I' + str(ROOT / 'runtime'), '-I' + str(REPO / 'runtime')]
        frameworks = ['-framework', 'Foundation', '-framework', 'Metal']
        subprocess.run(['clang', '-x', 'objective-c', '-std=c11', *include,
                        str(ROOT / 'tests/shader_sm3.c'), str(ROOT / 'runtime/vsemu.c'),
                        *frameworks, '-o', str(cls.binary)], check=True, capture_output=True)
        subprocess.run(['clang', '-fobjc-arc', *include, str(ROOT / 'tests/backend_sm3.m'),
                        str(ROOT / 'runtime/vsemu.c'), *frameworks,
                        '-framework', 'AppKit', '-framework', 'QuartzCore',
                        '-framework', 'GameController', '-framework', 'IOKit',
                        '-Wl,-undefined,dynamic_lookup', '-o', str(cls.backend)],
                       check=True, capture_output=True)
        subprocess.run(['clang', *include, str(ROOT / 'tests/backend_com_sm3.c'), str(ROOT / 'runtime/vsemu.c'),
                        '-Wl,-undefined,dynamic_lookup', '-o', str(cls.com)],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_reference_vectors_and_rejection(self):
        subprocess.run([str(self.binary)], check=True, capture_output=True)

    def test_com_shader_state_and_volume_layout(self):
        for mode in ('standard', 'full'):
            subprocess.run([str(self.com)], env={**os.environ, 'NFSMW_MODE': mode}, check=True, capture_output=True)

    def run_gpu(self, command):
        result = subprocess.run(command, capture_output=True)
        if result.returncode == 77:
            self.skipTest('Metal device unavailable inside this sandbox')
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_gpu_reference_vectors(self):
        self.run_gpu([str(self.binary), '--gpu'])

    def test_gpu_independent_color_outputs(self):
        self.run_gpu([str(self.binary), '--gpu-mrt'])

    def test_actual_hdr_luminance_and_mask_outputs(self):
        import hashlib
        candidates = [REPO / 'out/hq-extract/normalized/LOGIC/41/FX/hdr.fx.o',
                      REPO / 'out/installed/.nfsmw/full/fx/compiled/hdr.fx.o']
        code = None
        for candidate in candidates:
            if candidate.is_file():
                data = candidate.read_bytes()[0x3c20:0x3c20 + 1460]
                if hashlib.sha256(data).hexdigest() == 'db684c179b9da5df582ee9c5608ed698c5bd5593626bd9bf9cef309de6448fac':
                    code = data
                    break
        if code is None:
            self.skipTest('Pinned supplied HDR shader is unavailable')
        shader = self.directory / 'hdr-mrt.bin'
        shader.write_bytes(code)
        self.run_gpu([str(self.binary), '--gpu-hdr-mrt', str(shader)])
        translated = subprocess.run([str(self.binary), str(shader)], check=True, capture_output=True)
        prelude = subprocess.run([str(self.backend), '--prelude'], check=True, capture_output=True)
        source = self.directory / 'hdr-mrt.metal'
        source.write_bytes(prelude.stdout + translated.stdout)
        self.run_gpu([str(self.backend), '--depth-mrt', str(source)])

    def test_sparse_mrt_depth_wrappers(self):
        prelude = subprocess.run([str(self.backend), '--prelude'], check=True, capture_output=True)
        for mask in (3, 5, 8, 15):
            tokens = [0xffff0200]
            for color in range(4):
                if mask & (1 << color):
                    tokens += [0x02000001, 0x800f0800 | color, 0xa0e40000 | color]
            tokens.append(0xffff)
            shader = self.directory / f'mrt-{mask}.bin'
            shader.write_bytes(struct.pack('<' + 'I' * len(tokens), *tokens))
            translated = subprocess.run([str(self.binary), str(shader)], check=True, capture_output=True)
            source = self.directory / f'mrt-{mask}.metal'
            source.write_bytes(prelude.stdout + translated.stdout)
            self.run_gpu([str(self.backend), '--depth-mrt', str(source), str(mask)])

    def test_backend_projected_volume_and_generic_semantics(self):
        self.run_gpu([str(self.backend)])

    def test_enhanced_fixed_function_road_copy_keeps_its_stage_selector(self):
        binary=self.directory/'enhanced-fixed-copy'
        include=['-I'+str(ROOT/'runtime')]
        frameworks=['-framework', 'Foundation', '-framework', 'Metal', '-framework', 'AppKit', '-framework', 'QuartzCore', '-framework', 'GameController', '-framework', 'IOKit']
        subprocess.run(['clang','-fobjc-arc','-DNFS_ENHANCED=1',*include,str(ROOT/'tests/backend_sm3.m'),str(ROOT/'runtime/vsemu.c'),*frameworks,'-Wl,-undefined,dynamic_lookup','-o',str(binary)],check=True,capture_output=True)
        self.run_gpu([str(binary),'--fixed-road-copy'])

    def test_rain_pinned_resolution_uses_actual_com_vertices(self):
        vertices=self.directory/'rain-vertices.bin'
        subprocess.run([str(self.com)],env={**os.environ,'NFSMW_RAIN_VERTICES_OUT':str(vertices)},check=True,capture_output=True)
        self.run_gpu([str(self.backend),'--rain-vertices',str(vertices)])

    def corpus(self):
        corpus = REPO / 'out/hq-extract/normalized/LOGIC/41/FX'
        inventory = REPO / 'work/hq-x360/shader-inventory.json'
        if not corpus.is_dir() or not inventory.is_file():
            self.skipTest('Local HQ shader corpus is unavailable')
        translated = []
        for item in json.loads(inventory.read_text()):
            blob = (corpus / item['file'].split('$')[0]).read_bytes()
            for shader in item['shaders']:
                offset = int(shader['offset'], 16)
                code = blob[offset:offset + shader['bytes']]
                self.assertEqual(struct.unpack_from('<I', code)[0], int(shader['version'], 16))
                stem = item['file'].replace('$', '_') + shader['offset']
                binary = self.directory / (stem + '.bin')
                binary.write_bytes(code)
                result = subprocess.run([str(self.binary), str(binary)], capture_output=True)
                self.assertEqual(result.returncode, 0, f'{stem}: translator rejected: {result.stderr.decode()}')
                translated.append((stem, result.stdout.decode()))
        self.assertEqual(len(translated), 166)
        return translated

    def test_standard_resource_sampler4_compiles(self):
        executable = REPO / 'out/installed/.nfsmw/runtime.exe'
        if not executable.is_file():
            self.skipTest('Canonical Standard runtime is unavailable')
        import hashlib
        sys.path.insert(0, str(REPO))
        from tools.runtime_image import _parse_pe, STANDARD_RUNTIME_SHA256
        image = executable.read_bytes()
        if hashlib.sha256(image).hexdigest() != STANDARD_RUNTIME_SHA256:
            self.skipTest('Installed image is not canonical Standard')
        section = next(item for item in _parse_pe(image)['sections'] if item['name'] == b'.rsrc')
        offset = section['raw']
        limit = offset + section['raw_size']
        shaders = []
        while True:
            offset = image.find(b'\x00\x02\xff\xff', offset, limit)
            if offset < 0:
                break
            cursor, sampler4 = offset + 4, False
            while cursor + 4 <= limit:
                token = struct.unpack_from('<I', image, cursor)[0]
                opcode, count = token & 0xffff, (token >> 24) & 15
                if opcode == 0xffff:
                    if sampler4:
                        shaders.append(image[offset:cursor + 4])
                    break
                if opcode == 0xfffe:
                    cursor += 4 * (1 + ((token >> 16) & 0x7fff))
                    continue
                if not count or opcode > 97 or cursor + 4 * (count + 1) > limit:
                    break
                if opcode == 31 and count == 2:
                    register = struct.unpack_from('<I', image, cursor + 8)[0]
                    kind = ((register & 0x1800) >> 8) | ((register >> 28) & 7)
                    sampler4 |= kind == 10 and (register & 2047) == 4
                cursor += 4 * (count + 1)
            offset += 4
        self.assertTrue(shaders, 'Expected the Standard SM2 shader declaring s4')
        header = subprocess.run([str(self.backend), '--prelude'], check=True, capture_output=True).stdout.decode()
        for index, code in enumerate(shaders):
            binary = self.directory / f'standard-s4-{index}.bin'
            binary.write_bytes(code)
            result = subprocess.run([str(self.binary), str(binary)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            source = result.stdout.decode()
            self.assertIn('#define SMP4(', source)
            path = self.directory / f'standard-s4-{index}.metal'
            path.write_text(header + source)
            self.run_gpu([str(self.binary), '--metal', str(path)])

    def test_supplied_hq_corpus_translates(self):
        self.corpus()

    def test_all_standard_resource_pixels_translate_and_compile(self):
        shaders = standard_pixels()
        self.assertEqual(len(shaders), 51)
        self.assertTrue({0x50614,0x51694,0x527f0,0x577c4,0x57acc} <= {offset for offset, _ in shaders})
        header = subprocess.run([str(self.backend), '--prelude'], check=True, capture_output=True).stdout.decode()
        errors = []
        for offset, code in shaders:
            binary = self.directory / f'standard-{offset:x}.bin'
            binary.write_bytes(code)
            result = subprocess.run([str(self.binary), str(binary)], capture_output=True)
            if result.returncode:
                errors.append(f'{offset:x}: translator rejected')
                continue
            source = self.directory / f'standard-{offset:x}.metal'
            source.write_text(header + result.stdout.decode())
            compiled = subprocess.run([str(self.binary), '--metal', str(source)], capture_output=True)
            if compiled.returncode == 77:
                self.skipTest('Metal device unavailable inside this sandbox')
            if compiled.returncode:
                errors.append(f'{offset:x}: {compiled.stderr.decode()}')
            depth = subprocess.run([str(self.backend), '--depth', str(source)], capture_output=True)
            if depth.returncode:
                errors.append(f'{offset:x} depth variant: {depth.stderr.decode()}')
        self.assertFalse(errors, '\n'.join(errors))

    def test_supplied_hq_corpus_compiles_with_backend_prelude(self):
        translated = self.corpus()
        header = subprocess.run([str(self.backend), '--prelude'], check=True,
                                capture_output=True).stdout.decode()
        probe = self.directory / 'probe.metal'
        probe.write_text(header)
        self.run_gpu([str(self.binary), '--metal', str(probe)])

        def compile_shader(job):
            stem, source = job
            path = self.directory / (stem + '.metal')
            path.write_text(header + source)
            result = subprocess.run([str(self.binary), '--metal', str(path)], capture_output=True)
            if result.returncode:
                return f'{stem}: {result.stderr.decode()}'
            if 'fragment ' in source:
                mode = '--depth-mrt' if 'fragment PSMRT_' in source else '--depth'
                result = subprocess.run([str(self.backend), mode, str(path)], capture_output=True)
                if result.returncode:
                    return f'{stem} depth variant: {result.stderr.decode()}'
            return None

        with ThreadPoolExecutor(max_workers=8) as executor:
            errors = [error for error in executor.map(compile_shader, translated) if error]
        self.assertFalse(errors, '\n'.join(errors))


if __name__ == '__main__':
    unittest.main()
