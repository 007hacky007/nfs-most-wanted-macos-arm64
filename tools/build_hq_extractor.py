"""Build the pinned native HQ extractor, with explicit optional source download."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tarfile
import urllib.request

SOURCE_URL = 'https://codeload.github.com/psi29a/innoextract/tar.gz/8f317ad'
SOURCE_SHA256 = 'b9d6fadd35f3904d028174d7d041fc7e28af77c082ff10a2407e982e6419dead'
SOURCE_DIRECTORY = 'innoextract-8f317ad'


def patch_source(source):
    """Apply local fixes for 6.5+ slice headers, bounds and checksum display."""
    checksum_file = source / 'src/crypto/checksum.cpp'
    code = checksum_file.read_text()
    start = code.index('\t\tcase crypto::SHA256: {')
    end = code.index('\t\tcase crypto::PBKDF2_SHA256_XChaCha20:', start)
    section = code[start:end]
    # Altered source: fix upstream's truncated SHA-256 display; validation is correct.
    section = section.replace('checksum.sha1', 'checksum.sha256')
    if '// Altered source:' not in section:
        section = section.replace('case crypto::SHA256: {',
                                  'case crypto::SHA256: { // Altered source: print all 32 digest bytes.')
    checksum_file.write_text(code[:start] + section + code[end:])
    slice_file = source / 'src/stream/slice.cpp'
    code = slice_file.read_text()
    if "{ 'i', 'd', 's', 'k', 'b', '3', '2', 0x1a }" not in code:
        code = code.replace("\t{ 'i', 'd', 's', 'k', 'a', '3', '2', 0x1a },",
                            "\t{ 'i', 'd', 's', 'k', 'a', '3', '2', 0x1a },\n"
                            "\t{ 'i', 'd', 's', 'k', 'b', '3', '2', 0x1a }, // Altered source: Inno 6.5+ slices.")
    code = code.replace('for(size_t i = 0; boost::size(slice_ids); i++)',
                        'for(size_t i = 0; i < boost::size(slice_ids); i++)')
    code = code.replace('\tslice_size = util::load<boost::uint32_t>(ifs);',
                        "\t// Altered source: b32 slices store a 64-bit size.\n"
                        "\tboost::uint64_t stored_size = magic[4] == 'b' ? util::load<boost::uint64_t>(ifs)\n"
                        "\t                                           : util::load<boost::uint32_t>(ifs);\n"
                        "\tif(stored_size > std::numeric_limits<boost::uint32_t>::max()) {\n"
                        "\t\tthrow slice_error(\"slice larger than 4 GiB is unsupported\");\n"
                        "\t}\n\tslice_size = boost::uint32_t(stored_size);")
    slice_file.write_text(code)


def build_extractor(source_archive: Path, output: Path) -> Path:
    source_archive, output = Path(source_archive), Path(output)
    with source_archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError('unsupported innoextract source SHA-256')
    output.mkdir(parents=True, exist_ok=True)
    source = output / SOURCE_DIRECTORY
    if not source.exists():
        with tarfile.open(source_archive) as archive:
            archive.extractall(output, filter='data')
    patch_source(source)
    build = output / 'build'
    subprocess.run(['cmake', '-S', str(source), '-B', str(build),
                    '-DCMAKE_BUILD_TYPE=Release', '-DDEBUG=ON'], check=True)
    subprocess.run(['cmake', '--build', str(build), '-j', '8'], check=True)
    extractor = build / 'innoextract'
    subprocess.run([str(extractor), '--version'], check=True)
    return extractor


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-archive', type=Path)
    parser.add_argument('--output', type=Path, default=Path('out/tools/hq-extractor'))
    parser.add_argument('--download', action='store_true', help='explicitly download the pinned source archive')
    args = parser.parse_args()
    if args.download:
        args.output.mkdir(parents=True, exist_ok=True)
        args.source_archive = args.output / 'innoextract-source.tar.gz'
        with urllib.request.urlopen(SOURCE_URL) as src, args.source_archive.open('wb') as dst:
            dst.write(src.read())
    if args.source_archive is None:
        parser.error('provide --source-archive for an offline build or --download explicitly')
    print(build_extractor(args.source_archive, args.output))
