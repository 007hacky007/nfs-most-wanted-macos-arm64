#!/usr/bin/env python3
"""Build the extraction helpers NFSMW Builder bundles: innoextract and the RTPatch decoder.

For CI and maintainers only. Users of ./build.sh build their own extractor with Homebrew
tools; NFSMW Builder users get these prebuilt, so they need nothing but Apple's command
line tools. innoextract is built from the same pinned source and the same patch_source()
edits as tools/build_hq_extractor.py, linked statically against Boost and liblzma that are
built here from pinned sources for macOS 12. Every file the helpers later produce is still
checked against the pipeline's own SHA-256 pins.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_hq_extractor  # noqa: E402
import helpers  # noqa: E402
from patch_sources import fetch_patch  # noqa: E402

MIN_MACOS = '12.0'
ARCH = 'arm64'
# Pinned dependency sources. The SHA-256 values match the publishers' own checksums
# (boost_1_92_0.tar.gz.json on archives.boost.io, and Homebrew's xz 5.8.4 formula).
BOOST = {'version': '1.92.0', 'directory': 'boost_1_92_0',
         'url': 'https://archives.boost.io/release/1.92.0/source/boost_1_92_0.tar.gz',
         'sha256': 'c4a3b310ddd2472416e091067166b0713be97c63f38c212c484ada022fd296ce'}
XZ = {'version': '5.8.4', 'directory': 'xz-5.8.4',
      'url': 'https://github.com/tukaani-project/xz/releases/download/v5.8.4/xz-5.8.4.tar.gz',
      'sha256': '0014c7886930454fe8bd4228665b51af55eeae560ea135c9c4cd33f55b2591d9'}
# iostreams (with zlib and bzip2 from the SDK) also pulls in random, atomic and container.
BOOST_LIBRARIES = ('iostreams', 'filesystem', 'date_time', 'system', 'program_options',
                   'random', 'atomic', 'container')
FLAGS = f'-arch {ARCH} -mmacosx-version-min={MIN_MACOS}'
JOBS = str(os.cpu_count() or 4)


def environment():
    env = dict(os.environ, MACOSX_DEPLOYMENT_TARGET=MIN_MACOS)
    for name in ('CPATH', 'LIBRARY_PATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'PKG_CONFIG_PATH'):
        env.pop(name, None)
    return env


def run(command, **options):
    print('+ ' + ' '.join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), check=True, env=options.pop('env', environment()), **options)


def fetch(source, downloads):
    """Download a pinned source archive once; the SHA-256 decides, never the server."""
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / source['url'].rsplit('/', 1)[1]
    if archive.is_file() and helpers.sha256(archive) == source['sha256']:
        return archive
    partial = archive.with_name(archive.name + '.part')
    with urllib.request.urlopen(source['url'], timeout=60) as response, partial.open('wb') as output:
        shutil.copyfileobj(response, output, 1 << 20)
    if helpers.sha256(partial) != source['sha256']:
        partial.unlink()
        raise SystemExit(f'{archive.name} does not match its pinned SHA-256')
    partial.replace(archive)
    return archive


def unpack(archive, work, directory):
    target = work / directory
    shutil.rmtree(target, ignore_errors=True)
    with tarfile.open(archive) as tar:
        tar.extractall(work, filter='data')
    return target


def dependency_key():
    return json.dumps({'boost': BOOST['sha256'], 'xz': XZ['sha256'], 'macos': MIN_MACOS,
                       'libraries': BOOST_LIBRARIES})


def build_dependencies(prefix, work, downloads):
    """Static liblzma and Boost in `prefix`; reused while the pins and flags are unchanged."""
    marker = prefix / '.nfsmw-helpers-deps'
    if marker.is_file() and marker.read_text() == dependency_key():
        print(f'Reusing Boost {BOOST["version"]} and xz {XZ["version"]} in {prefix}', flush=True)
        return
    shutil.rmtree(prefix, ignore_errors=True)
    prefix.mkdir(parents=True)
    xz = unpack(fetch(XZ, downloads), work, XZ['directory'])
    run(['./configure', f'--prefix={prefix}', '--disable-shared', '--enable-static', '--disable-xz',
         '--disable-xzdec', '--disable-lzmadec', '--disable-lzmainfo', '--disable-scripts', '--disable-doc',
         '--disable-nls', f'CFLAGS=-O2 {FLAGS}', f'LDFLAGS={FLAGS}'], cwd=xz)
    run(['make', f'-j{JOBS}', 'install'], cwd=xz)
    boost = unpack(fetch(BOOST, downloads), work, BOOST['directory'])
    run(['./bootstrap.sh', '--with-toolset=clang', '--with-libraries=' + ','.join(BOOST_LIBRARIES)], cwd=boost)
    run(['./b2', 'install', f'--prefix={prefix}', f'-j{JOBS}', 'toolset=clang', 'link=static',
         'variant=release', 'threading=multi', 'runtime-link=shared', 'architecture=arm', 'address-model=64',
         f'cflags={FLAGS}', f'cxxflags={FLAGS} -std=c++17', f'linkflags={FLAGS}', '-sNO_LZMA=1', '-sNO_ZSTD=1',
         *[f'--with-{name}' for name in BOOST_LIBRARIES]], cwd=boost)
    marker.write_text(dependency_key())


def build_innoextract(prefix, work, downloads, output):
    archive = fetch_patch('hq-extractor', downloads)
    source = unpack(archive, work, build_hq_extractor.SOURCE_DIRECTORY)
    build_hq_extractor.patch_source(source)
    build = work / 'innoextract-build'
    shutil.rmtree(build, ignore_errors=True)
    env = dict(environment(), PKG_CONFIG_LIBDIR=str(prefix / 'lib/pkgconfig'))
    run(['cmake', '-S', source, '-B', build, '-DCMAKE_BUILD_TYPE=Release', '-DDEBUG=ON', '-DBUILD_TESTS=OFF',
         '-DUSE_STATIC_LIBS=OFF', '-DBoost_USE_STATIC_LIBS=ON', '-DLZMA_USE_STATIC_LIBS=ON',
         f'-DBoost_ROOT={prefix}', f'-DCMAKE_PREFIX_PATH={prefix}', f'-DCMAKE_OSX_ARCHITECTURES={ARCH}',
         f'-DCMAKE_OSX_DEPLOYMENT_TARGET={MIN_MACOS}', '-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew;/usr/local'],
        env=env)
    found = re.findall(r'^\w*(?:LIBRARY\w*|INCLUDE_DIR|_DIR):(?:FILE)?PATH=(.*)$',
                       (build / 'CMakeCache.txt').read_text(), re.M)
    if any(value.startswith(('/opt/homebrew', '/usr/local')) for value in found):
        raise SystemExit('innoextract found Homebrew libraries; only the pinned Boost and xz may be used')
    log = run(['cmake', '--build', build, '-j', JOBS], env=env, capture_output=True, text=True)
    sys.stdout.write(log.stdout[-4000:])
    if 'built for newer' in log.stdout + log.stderr:
        raise SystemExit('innoextract links objects built for a newer macOS than ' + MIN_MACOS)
    shutil.copyfile(build / 'innoextract', output)
    output.chmod(0o755)


def build_decoder(output):
    log = run(['rustc', '--edition=2021', '-O', '--target', 'aarch64-apple-darwin',
               ROOT / 'tools/rtpatch_decode.rs', '-o', output], capture_output=True, text=True)
    if 'built for newer' in log.stderr:
        raise SystemExit('the decoder links objects built for a newer macOS than ' + MIN_MACOS)


def minos(binary):
    text = run(['otool', '-l', binary], capture_output=True, text=True).stdout
    block = text.split('LC_BUILD_VERSION', 1)[1]
    return re.search(r'minos (\S+)', block).group(1)


def check(binary):
    found = minos(binary)
    if found != MIN_MACOS:
        raise SystemExit(f'{binary.name} targets macOS {found}, expected {MIN_MACOS}')
    lines = run(['otool', '-L', binary], capture_output=True, text=True).stdout.splitlines()[1:]
    for line in lines:
        library = line.strip().split(' (', 1)[0]
        if not library.startswith(('/usr/lib/', '/System/')):
            raise SystemExit(f'{binary.name} links {library}; only /usr/lib and /System are allowed')
    run(['codesign', '--verify', '--strict', binary])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, required=True, help='folder for innoextract, rtpatch-decode, helpers.json')
    parser.add_argument('--work', type=Path, default=ROOT / 'out/helpers-work', help='scratch folder (sources, builds)')
    parser.add_argument('--deps', type=Path, help='prefix for the static Boost and xz (default WORK/deps; CI caches it)')
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.uname().machine != 'arm64':
        raise SystemExit('helpers are built on an Apple Silicon Mac')
    work, output = args.work.resolve(), args.output.resolve()
    deps = (args.deps or work / 'deps').resolve()
    downloads = work / 'downloads'
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    build_dependencies(deps, work, downloads)
    innoextract, decoder = output / 'innoextract', output / 'rtpatch-decode'
    build_innoextract(deps, work, downloads, innoextract)
    build_decoder(decoder)
    for binary in (innoextract, decoder):
        run(['codesign', '--force', '--sign', '-', binary])
        check(binary)
    version = run([innoextract, '--version'], capture_output=True, text=True).stdout
    if '6.6.1' not in version:
        raise SystemExit('innoextract does not support Inno Setup 6.6.1:\n' + version)
    usage = subprocess.run([str(decoder)], capture_output=True, text=True)
    if usage.returncode != 1 or 'expected input' not in usage.stderr:
        raise SystemExit('the RTPatch decoder does not start')
    sources = helpers.expected_sources()
    manifest = {'innoextract': {'sha256': helpers.sha256(innoextract), **sources['innoextract'],
                                'boost': f'{BOOST["version"]} {BOOST["sha256"]}',
                                'xz': f'{XZ["version"]} {XZ["sha256"]}', 'minos': MIN_MACOS},
                'rtpatch-decode': {'sha256': helpers.sha256(decoder), **sources['rtpatch-decode'],
                                   'minos': MIN_MACOS}}
    (output / 'helpers.json').write_text(json.dumps(manifest, indent=2) + '\n')
    helpers.load(output)
    print('Helpers ready in ' + str(output))


if __name__ == '__main__':
    main()
