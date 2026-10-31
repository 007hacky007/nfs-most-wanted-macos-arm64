"""Verify the prebuilt extraction helpers that NFSMW Builder bundles (built by tools/build_helpers.py)."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('innoextract', 'rtpatch-decode')
STALE = 'These build tools do not match this version. Download NFSMW Builder again.'
INCOMPLETE = 'This copy of NFSMW Builder is incomplete. Download it again.'


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def decoder_source_sha256(root=ROOT):
    """One digest over the decoder and its codec, the two files rustc compiles."""
    digest = hashlib.sha256()
    for relative in ('tools/rtpatch_decode.rs', 'third_party/rtpatch/codec.rs'):
        digest.update(Path(root, relative).read_bytes())
    return digest.hexdigest()


def expected_sources(root=ROOT):
    """What the helpers must have been built from, computed from this tree."""
    try:
        from .build_hq_extractor import SOURCE_SHA256
    except ImportError:
        from build_hq_extractor import SOURCE_SHA256
    return {'innoextract': {'source_sha256': SOURCE_SHA256,
                            'patch_sha256': sha256(Path(root, 'tools/build_hq_extractor.py'))},
            'rtpatch-decode': {'source_sha256': decoder_source_sha256(root)}}


def load(directory, root=ROOT) -> dict:
    """Return {'innoextract': Path, 'rtpatch-decode': Path} after checking every pin in helpers.json."""
    directory = Path(directory)
    try:
        manifest = json.loads((directory / 'helpers.json').read_text())
    except (OSError, ValueError):
        raise ValueError(INCOMPLETE) from None
    expected = expected_sources(root)
    found = {}
    for name in NAMES:
        record, binary = manifest.get(name), directory / name
        if not isinstance(record, dict) or binary.is_symlink() or not binary.is_file():
            raise ValueError(INCOMPLETE)
        if sha256(binary) != record.get('sha256'):
            raise ValueError(INCOMPLETE)
        if any(record.get(key) != value for key, value in expected[name].items()):
            raise ValueError(STALE)
        found[name] = binary.resolve()
    return found
