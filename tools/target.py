"""Fingerprinted Most Wanted target and validated hidden relocation recovery."""
from pathlib import Path
import hashlib
import json
import struct
import pefile
try:
    from .install_game import EXE_SHA, HQ_EXE_SHA, OFFICIAL_EXE_SHA, D3DX_SHA, verify_binary
except ImportError:
    from install_game import EXE_SHA, HQ_EXE_SHA, OFFICIAL_EXE_SHA, D3DX_SHA, verify_binary

D3DX_BASE = 0x02000000

# Windows x86 callee-cleaned argument slots. MSVCRT is cdecl, handled separately.
IMPORT_ARGS = {
    '#6': 2, 'CreateProcessA': 10, 'CreateWaitableTimerA': 3,
    'FatalAppExitA': 2, 'GetDateFormatA': 6, 'GetKeyState': 1,
    'GetKeyboardLayout': 1, 'GetTimeFormatA': 6, 'GlobalMemoryStatusEx': 1,
    'HeapValidate': 3, 'MapVirtualKeyExA': 3, 'QueueUserAPC': 3,
    'SendInput': 3, 'SetWaitableTimer': 6, 'ToUnicode': 6,
    'WSACloseEvent': 1, 'WSACreateEvent': 0, 'WSAGetOverlappedResult': 5,
    'WSARecv': 7, 'WSARecvFrom': 9, 'WSAResetEvent': 1, 'WSASetEvent': 1,
    'WSAWaitForMultipleEvents': 5,
    'waveInAddBuffer': 3, 'waveInClose': 1, 'waveInGetDevCapsA': 3,
    'waveInGetNumDevs': 0, 'waveInGetPosition': 3, 'waveInOpen': 6,
    'waveInPrepareHeader': 3, 'waveInReset': 1, 'waveInStart': 1,
    'waveInStop': 1, 'waveInUnprepareHeader': 3, 'waveOutClose': 1,
    'waveOutGetDevCapsA': 3, 'waveOutGetNumDevs': 0, 'waveOutGetPosition': 3,
    'waveOutOpen': 6, 'waveOutPrepareHeader': 3, 'waveOutReset': 1,
    'waveOutSetVolume': 2, 'waveOutUnprepareHeader': 3, 'waveOutWrite': 3,
    'D3DXCreateEffectFromResourceA': 9, 'D3DXCreateEffectPool': 1,
    'D3DXMatrixInverse': 3, 'D3DXMatrixMultiply': 3, 'D3DXMatrixOrthoLH': 4,
    'D3DXMatrixPerspectiveLH': 4, 'D3DXMatrixTranslation': 4,
    'D3DXMatrixTranspose': 2, 'D3DXVec3Normalize': 2, 'D3DXVec3Transform': 3,
    'D3DXVec3TransformCoordArray': 6, 'D3DXVec3TransformNormal': 3,
    'D3DXVec4Transform': 3,
    'GetCurrentObject': 2, 'TranslateCharsetInfo': 3, 'ExtTextOutW': 8, 'SetTextAlign': 2,
    'GetOutlineTextMetricsA': 3, 'GetGlyphOutlineW': 7, 'CreateFontIndirectW': 1,
    'CreateFontIndirectA': 1, 'GetFontLanguageInfo': 1, 'GetTextMetricsW': 2,
    'GetCharacterPlacementW': 6, 'GetCharacterPlacementA': 6, 'CreateDIBSection': 6,
    'GetGlyphOutlineA': 7, 'GetTextMetricsA': 2, 'GetObjectW': 3,
    'DeleteFileW': 1, 'FreeResource': 1, 'CreateFileW': 7, 'IsDBCSLeadByte': 1,
    'GetTempPathA': 2, 'GetTempFileNameA': 4, 'MoveFileW': 2,
    'GetTempFileNameW': 4, 'ExpandEnvironmentStringsA': 3, 'DisableThreadLibraryCalls': 1,
}


def check_module_range(base, size):
    if base % 0x10000 or size <= 0 or base < 0x01000000 or base + size > 0x03000000:
        raise ValueError('DLL range overlaps a reserved guest region')


def recover_relocations(pe):
    candidates = [s for s in pe.sections if not s.Name.strip(b'\0 ')]
    if len(candidates) != 1:
        raise ValueError('expected one hidden relocation section')
    blob = candidates[0].get_data()
    off = 0
    slots = []
    ib = pe.OPTIONAL_HEADER.ImageBase
    end = ib + pe.OPTIONAL_HEADER.SizeOfImage
    while off + 8 <= len(blob):
        page, size = struct.unpack_from('<II', blob, off)
        if page == size == 0:
            break
        if page % 4096 or size < 8 or size % 2 or off + size > len(blob):
            raise ValueError('malformed relocation block')
        for at in range(off + 8, off + size, 2):
            word = struct.unpack_from('<H', blob, at)[0]
            kind = word >> 12
            if kind == 0:
                continue
            if kind != 3:
                raise ValueError('unsupported relocation type')
            rva = page + (word & 4095)
            value = pe.get_dword_at_rva(rva)
            if value is None or not ib <= value < end:
                raise ValueError('relocation does not hold an in-image pointer')
            slots.append(ib + rva)
        off += size
    if not slots or len(set(slots)) != len(slots):
        raise ValueError('missing or duplicate relocation slots')
    return sorted(slots)


def select_image(game):
    game = Path(game)
    image = game / 'speed.exe'
    data = image.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest == OFFICIAL_EXE_SHA:
        image = game / '.nfsmw/runtime.exe'
        data = image.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
    if digest not in (EXE_SHA, HQ_EXE_SHA):
        raise ValueError('unsupported native runtime image SHA-256')
    verify_binary(data, digest)
    return image


def prepare(game):
    game = Path(game)
    image = select_image(game)
    exe = image.read_bytes()
    exe_sha = hashlib.sha256(exe).hexdigest()
    dll = (game / 'd3dx9_26.dll').read_bytes()
    verify_binary(dll, D3DX_SHA)
    pe = pefile.PE(data=exe)
    dpe = pefile.PE(data=dll)
    check_module_range(D3DX_BASE, dpe.OPTIONAL_HEADER.SizeOfImage)
    slots = recover_relocations(pe)
    Path('out').mkdir(exist_ok=True)
    Path('out/target-image.txt').write_text(str(image) + '\n')
    Path('out/relocs.txt').write_text('\n'.join(f'{a:08x}' for a in slots) + '\n')
    text = next(s for s in pe.sections if s.Name.rstrip(b'\0') == b'.text')
    target = {'sha256': exe_sha, 'base': pe.OPTIONAL_HEADER.ImageBase,
              'image_size': pe.OPTIONAL_HEADER.SizeOfImage,
              'entry': pe.OPTIONAL_HEADER.ImageBase + pe.OPTIONAL_HEADER.AddressOfEntryPoint,
              'text': pe.OPTIONAL_HEADER.ImageBase + text.VirtualAddress,
              'text_size': text.Misc_VirtualSize, 'relocations': len(slots),
              'd3dx_base': D3DX_BASE, 'd3dx_sha256': D3DX_SHA}
    Path('out/target.json').write_text(json.dumps(target, indent=2) + '\n')
    Path('runtime/target.h').write_text(
        '#ifndef NFSMW_TARGET_H\n#define NFSMW_TARGET_H\n' +
        '\n'.join(f'#define MW_{key.upper()} 0x{target[key]:08x}u'
                  for key in ('base', 'image_size', 'entry', 'text', 'text_size', 'd3dx_base')) +
        f'\n#define MW_EXE_SHA "{exe_sha}"\n#define MW_D3DX_SHA "{D3DX_SHA}"\n#endif\n')
    print(f'Most Wanted: {len(slots)} validated relocations; entry {target["entry"]:#x}')
    return target


if __name__ == '__main__':
    import sys
    prepare(sys.argv[1] if len(sys.argv) > 1 else 'game')
