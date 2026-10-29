"""Reconstruct the supported PC runtime from supplied HQ code and official resources."""
import argparse
import hashlib
from pathlib import Path
import struct
import tempfile

HQ_IMAGE_SHA256 = '8393f3487e3e024d6c2196d8adcd3f5b1b38077a893d9161a6f9ac61d587fa19'
OFFICIAL_IMAGE_SHA256 = 'e8019e0d7b706beba5ec648a50108a9a13346695eba9ebe58b6d796260d3c4eb'
STANDARD_RUNTIME_SHA256 = '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c'


def _parse_pe(data):
    try:
        if len(data) < 64 or data[:2] != b'MZ':
            raise ValueError('expected a PE executable')
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        if data[pe:pe + 6] != b'PE\0\0\x4c\x01':
            raise ValueError('expected an i386 PE executable')
        count = struct.unpack_from('<H', data, pe + 6)[0]
        opt_size = struct.unpack_from('<H', data, pe + 20)[0]
        opt = pe + 24
        if opt_size < 224 or struct.unpack_from('<H', data, opt)[0] != 0x10b:
            raise ValueError('expected a PE32 optional header')
        table = opt + opt_size
        if not 1 <= count <= 96 or table + count * 40 > len(data):
            raise ValueError('invalid PE section table')
        sections = []
        for index in range(count):
            header = table + index * 40
            virtual_size, rva, raw_size, raw = struct.unpack_from('<IIII', data, header + 8)
            if raw + raw_size > len(data):
                raise ValueError('PE section extends beyond the file')
            sections.append({'name': data[header:header + 8].rstrip(b'\0'), 'header': header,
                             'virtual_size': virtual_size, 'rva': rva, 'raw_size': raw_size, 'raw': raw,
                             'flags': struct.unpack_from('<I', data, header + 36)[0]})
        return {'pe': pe, 'optional': opt, 'sections': sections,
                'section_alignment': struct.unpack_from('<I', data, opt + 32)[0],
                'size_of_image': struct.unpack_from('<I', data, opt + 56)[0],
                'entrypoint': struct.unpack_from('<I', data, opt + 16)[0],
                'imports': struct.unpack_from('<II', data, opt + 104),
                'resource': struct.unpack_from('<II', data, opt + 112)}
    except (struct.error, OverflowError) as error:
        raise ValueError('truncated PE headers') from error


def _repair_resources(hq, official):
    """Keep HQ code and restore the supported original resource and header layout."""
    before, original = _parse_pe(hq), _parse_pe(official)
    sections = before['sections']
    if (len(sections) != 5 or len(original['sections']) < 5
            or [section['name'] for section in sections] != [b'.text', b'.rdata', b'.data', b'.rsrc', b'        ']):
        raise ValueError('unsupported runtime section layout')
    resource, tail = sections[3:]
    replacement, original_tail = original['sections'][3:5]
    if (replacement['name'] != b'.rsrc' or original_tail['name'] != tail['name']
            or resource['rva'] != replacement['rva'] or resource['raw'] != replacement['raw']
            or tail['raw'] != resource['raw'] + resource['raw_size']
            or tail['raw'] + tail['raw_size'] != len(hq)
            or not tail['flags'] & 0x02000000 or tail['flags'] & 0x20000000):
        raise ValueError('unsupported resource or discardable section layout')
    delta = replacement['raw_size'] - resource['raw_size']
    fixed = bytearray(hq[:resource['raw']]
                      + official[replacement['raw']:replacement['raw'] + replacement['raw_size']]
                      + hq[tail['raw']:])
    struct.pack_into('<IIII', fixed, resource['header'] + 8,
                     replacement['virtual_size'], replacement['rva'], replacement['raw_size'], replacement['raw'])
    struct.pack_into('<I', fixed, tail['header'] + 12, original_tail['rva'])
    struct.pack_into('<I', fixed, tail['header'] + 20, tail['raw'] + delta)
    opt = before['optional']
    struct.pack_into('<II', fixed, opt + 112, *original['resource'])
    struct.pack_into('<I', fixed, opt + 8, struct.unpack_from('<I', hq, opt + 8)[0] + delta)
    # Preserve the supported image's unrounded end; the native loader aligns its mapping.
    struct.pack_into('<I', fixed, opt + 56, original_tail['rva'] + tail['virtual_size'])
    struct.pack_into('<I', fixed, opt + 64, 0)
    characteristics = struct.unpack_from('<H', fixed, before['pe'] + 22)[0]
    struct.pack_into('<H', fixed, before['pe'] + 22, characteristics & ~0x20)
    after = _parse_pe(fixed)
    for section in sections[:3]:
        start, size = section['raw'], section['raw_size']
        if fixed[start:start + size] != hq[start:start + size]:
            raise ValueError('runtime code or data changed during resource repair')
    if (after['entrypoint'] != before['entrypoint'] or after['imports'] != before['imports']
            or replacement['rva'] + replacement['virtual_size'] > original_tail['rva']):
        raise ValueError('invalid repaired runtime layout')
    return bytes(fixed)


def resource_hashes(data):
    """Hash every PE resource payload by its type/name/language path, without loading it."""
    image = _parse_pe(data)

    def offset(rva, size):
        for section in image['sections']:
            relative = rva - section['rva']
            if 0 <= relative and relative + size <= section['raw_size']:
                return section['raw'] + relative
        raise ValueError('resource data extends beyond its section')

    resource = next((section for section in image['sections'] if section['name'] == b'.rsrc'), None)
    if resource is None:
        raise ValueError('resource section missing')
    root = offset(image['resource'][0], 16)
    limit = resource['raw'] + resource['raw_size']
    found = {}

    def read(relative, size):
        start = root + relative
        if relative < 0 or start + size > limit:
            raise ValueError('resource directory extends beyond its section')
        return start

    def walk(relative, path, ancestors):
        if relative in ancestors or len(path) > 8:
            raise ValueError('cyclic resource directory')
        header = read(relative, 16)
        count = sum(struct.unpack_from('<HH', data, header + 12))
        entries = read(relative + 16, count * 8)
        for index in range(count):
            name, target = struct.unpack_from('<II', data, entries + index * 8)
            if name & 0x80000000:
                name_offset = name & 0x7fffffff
                length = struct.unpack_from('<H', data, read(name_offset, 2))[0]
                start = read(name_offset + 2, length * 2)
                name = data[start:start + length * 2].decode('utf-16le')
            key = (*path, name)
            if target & 0x80000000:
                walk(target & 0x7fffffff, key, ancestors | {relative})
            else:
                rva, size = struct.unpack_from('<II', data, read(target, 16))
                start = offset(rva, size)
                if key in found:
                    raise ValueError('duplicate resource path')
                found[key] = hashlib.sha256(data[start:start + size]).hexdigest()
    walk(0, (), set())
    return found


def build_standard_runtime(hq_image: Path, official_image: Path, output: Path) -> dict:
    """Reconstruct exactly the supported 80774... image from two fingerprinted inputs."""
    hq, official = Path(hq_image).read_bytes(), Path(official_image).read_bytes()
    for name, data, expected in (('HQ', hq, HQ_IMAGE_SHA256), ('official', official, OFFICIAL_IMAGE_SHA256)):
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f'unsupported {name} image SHA-256')
    fixed = _repair_resources(hq, official)
    if hashlib.sha256(fixed).hexdigest() != STANDARD_RUNTIME_SHA256:
        raise ValueError('reconstructed runtime SHA-256 mismatch')
    resources = resource_hashes(official)
    if len(resources) != 33 or resource_hashes(fixed) != resources:
        raise ValueError('reconstructed runtime resources differ from the official image')
    output = Path(output)
    result = {'sha256': STANDARD_RUNTIME_SHA256, 'size': len(fixed), 'resources': len(resources)}
    if output.exists():
        if output.is_symlink() or output.read_bytes() != fixed:
            raise FileExistsError('runtime output already exists with different content')
        return result
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.nfsmw-runtime-', dir=output.parent) as temporary:
        staged = Path(temporary) / 'runtime.exe'
        staged.write_bytes(fixed)
        staged.replace(output)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hq_image', type=Path)
    parser.add_argument('official_image', type=Path)
    parser.add_argument('output', type=Path)
    arguments = parser.parse_args()
    print(build_standard_runtime(arguments.hq_image, arguments.official_image, arguments.output))
