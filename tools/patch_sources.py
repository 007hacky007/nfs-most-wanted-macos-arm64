"""Fetch pinned public patch payloads into a verified local cache."""
from dataclasses import dataclass
import errno
import hashlib
import html.parser
import http.client
import http.cookiejar
import fcntl
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = 'NFSMW-native-build'
BLOCK_BYTES = 1024 * 1024
MAX_LISTING_BYTES = 1024 * 1024
MAX_MIRRORS = 8
# Large payloads resume after a dropped connection and fail only after a stall.
RESUMABLE_BYTES = 100 * 1024 * 1024
STALL_SECONDS = 120
PROGRESS_SECONDS = 0.5

@dataclass(frozen=True)
class PatchSpec:
    filename: str
    size: int
    sha256: str
    urls: tuple[str, ...]
    kind: str = 'direct'

SOURCES = {
    'hq-extractor': PatchSpec('innoextract-source.tar.gz',218830,
        'b9d6fadd35f3904d028174d7d041fc7e28af77c082ff10a2407e982e6419dead',(
            'https://codeload.github.com/psi29a/innoextract/tar.gz/8f317ad',)),
    'official-1.3': PatchSpec('nfsmwpatch1.3.exe', 12777356,
        '4c858e9b63ae2f856af7f1c090d5ce3d8c75246e9c0f7018ff57efb87addd0ef', (
            'https://largedownloads.ea.com/pub/patches/nfsmwpatch1.3.exe',
            'https://dl1.nfsplanet.com/nfsmw/patches/nfsmwpatch1.3.exe')),
    'widescreen': PatchSpec('NFSMostWanted.WidescreenFix.zip', 8911715,
        '7be912197ac19134d5a64dfe61225e4ef85d612c4f64b96045727c3bf6735df4', (
            'https://api.github.com/repos/ThirteenAG/WidescreenFixesPack/releases/assets/558912001',), 'github'),
    'mw-hq': PatchSpec('MW_HQ_1.20.9.zip', 3337473092,
        '1ff919737829ca46179c90740d32f6fed6797ad6b88a8daeaa6ecf255d184963', (
            'https://www.moddb.com/downloads/start/233611',), 'moddb'),
    'directx': PatchSpec('directx_Jun2010_redist.exe', 100275120,
        '053f76dcbb28802e23341b6a787e3b0791c0fa5c8d4d011b1044172dbf89c73b', (
            'https://download.microsoft.com/download/8/4/a/84a35bf1-dafe-4ae8-82af-ad2ae20b6b14/directx_Jun2010_redist.exe',)),
}

class DownloadError(RuntimeError):
    """No verified payload was published; messages exclude temporary URLs."""


def _https(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise DownloadError('Only anonymous HTTPS sources are allowed')
    return parsed


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _directory(path, *, create=True):
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if not create:
                raise
            current.mkdir(exist_ok=True)
            mode = current.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise DownloadError('Cache directories must not be symlinks or other files')
    return absolute


def _state(name, directory):
    try:
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise DownloadError('Cached payload must be a regular file, never a symlink')
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _verified(spec, directory, expected, name=None):
    name = spec.filename if name is None else name
    if expected is None or expected[2] != spec.size:
        return False
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    with os.fdopen(fd, 'rb') as stream:
        digest = hashlib.sha256()
        total = 0
        while chunk := stream.read(min(BLOCK_BYTES, spec.size - total + 1)):
            total += len(chunk)
            if total > spec.size:
                return False
            digest.update(chunk)
    if _state(name, directory) != expected:
        raise DownloadError('Cached payload changed during verification')
    return total == spec.size and digest.hexdigest() == spec.sha256


class RangeRefused(DownloadError):
    """The source cannot continue the kept partial download."""


def _open(client, url, headers, timeout, statuses=(200,)):
    _https(url)
    try:
        response = client.open(urllib.request.Request(url, headers=headers), timeout=timeout)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 416 and 'Range' in headers:
            raise RangeRefused('HTTP source cannot continue the partial download') from None
        raise DownloadError('HTTP source refused the request') from None
    try:
        _https(response.geturl())
        if response.status not in statuses:
            raise DownloadError('Expected a complete HTTP response')
    except BaseException:
        response.close()
        raise
    return response


def _read(response, count, deadline):
    if time.monotonic() >= deadline:
        raise DownloadError('Download exceeded its time limit')
    # HTTPResponse.read1 avoids waiting for a full block from a trickling peer.
    chunk = getattr(response, 'read1', response.read)(count)
    if time.monotonic() >= deadline:
        raise DownloadError('Download exceeded its time limit')
    return chunk


class _Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            self.links.extend(value for key, value in attrs if key.lower() == 'href' and value)


_FAILURES = (DownloadError, OSError, ValueError, http.client.HTTPException)


def _candidates(key, spec, client, headers):
    if spec.kind != 'moddb':
        for index, url in enumerate(spec.urls):
            yield url, headers, 6 if key == 'official-1.3' and index == 0 else 30
        return
    start = spec.urls[0]
    seen = set()
    for listing in (start, start + '/all'):
        if len(seen) >= MAX_MIRRORS:
            return
        try:
            deadline = time.monotonic() + 30
            with _open(client, listing, headers, 30) as response:
                page = bytearray()
                while chunk := _read(response, MAX_LISTING_BYTES - len(page) + 1, deadline):
                    page.extend(chunk)
                    if len(page) > MAX_LISTING_BYTES:
                        raise DownloadError('Publisher mirror listing exceeds its size limit')
            parser = _Links()
            parser.feed(page.decode('utf-8', errors='replace'))
        except _FAILURES:
            continue
        for link in parser.links:
            try:
                mirror = urllib.parse.urljoin(start, link)
                parsed = urllib.parse.urlsplit(mirror)
            except ValueError:
                continue
            parts = parsed.path.strip('/').split('/')
            if (parsed.scheme != 'https' or parsed.hostname not in ('www.moddb.com', 'moddb.com')
                    or parsed.username is not None or parsed.password is not None
                    or len(parts) != 5 or parts[:3] != ['downloads', 'mirror', '233611']
                    or not parts[3].isdigit() or not parts[4] or mirror in seen):
                continue
            seen.add(mirror)
            yield mirror, {**headers, 'Referer': listing}, 60
            if len(seen) >= MAX_MIRRORS:
                return


class _Progress:
    """Calls progress(received, total) at most every PROGRESS_SECONDS, plus a final call."""
    def __init__(self, callback, total):
        self.callback, self.total, self.last = callback, total, None
    def __call__(self, received, final=False):
        if self.callback is None:
            return
        now = time.monotonic()
        if final or self.last is None or now - self.last >= PROGRESS_SECONDS:
            self.last = now
            self.callback(received, self.total)


def _publish(name, spec, cache, directory, original):
    # Recheck the requested directory and destination before publication.
    _directory(cache, create=False)
    actual, opened = cache.stat(), os.fstat(directory)
    if (actual.st_dev, actual.st_ino) != (opened.st_dev, opened.st_ino):
        raise DownloadError('Cache directory changed during download')
    if _state(spec.filename, directory) != original:
        raise DownloadError('Cache destination changed during download')
    if original is None:
        os.link(name, spec.filename, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    else:
        os.replace(name, spec.filename, src_dir_fd=directory, dst_dir_fd=directory)
    return cache / spec.filename


def _check_headers(response, expected_length):
    length = response.headers.get('Content-Length')
    encoding = response.headers.get('Content-Encoding', 'identity').lower()
    if (length is not None and int(length) != expected_length) or encoding != 'identity':
        raise DownloadError('Response length or encoding does not match the pinned payload')


def _unlink(name, directory):
    try:
        os.unlink(name, dir_fd=directory)
    except FileNotFoundError:
        pass


def _download(client, candidate, spec, cache, directory, original, progress=None, partial=None):
    if partial is not None:
        return _resumable(client, candidate, spec, cache, directory, original, progress, partial)
    url, headers, timeout = candidate
    temporary = '.' + spec.filename + '.' + secrets.token_hex(8) + '.part'
    created = False
    report = _Progress(progress, spec.size)
    try:
        budget = 20 if timeout == 6 else min(7200, max(300, spec.size / (256 * 1024)))
        deadline = time.monotonic() + budget
        with _open(client, url, headers, timeout) as response:
            _check_headers(response, spec.size)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            created = True
            with os.fdopen(fd, 'wb') as output:
                digest = hashlib.sha256()
                total = 0
                while chunk := _read(response, min(BLOCK_BYTES, spec.size - total + 1), deadline):
                    total += len(chunk)
                    if total > spec.size:
                        raise DownloadError('Response exceeds the pinned payload size')
                    output.write(chunk)
                    digest.update(chunk)
                    report(total)
                if total != spec.size or digest.hexdigest() != spec.sha256:
                    raise DownloadError('Payload size or SHA-256 does not match its pin')
                output.flush()
                os.fsync(output.fileno())
        result = _publish(temporary, spec, cache, directory, original)
        report(spec.size, final=True)
        return result
    finally:
        if created:
            _unlink(temporary, directory)


def _partial_name(spec):
    return '.' + spec.filename + '.partial'


class DiskFull(DownloadError):
    """The cache volume ran out of space; another mirror would not help."""


class DownloadBusy(DownloadError):
    """Another process holds the partial download of the same payload."""


class _Partial:
    """The kept partial download of a large payload: opened, locked and hashed once per fetch.

    `kept` bytes on disk always match `digest`; every attempt first cuts the file back to
    `kept`, so bytes of a failed write never count.
    """
    def __init__(self, spec, directory):
        self.spec, self.name = spec, _partial_name(spec)
        fd = os.open(self.name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        self.file = os.fdopen(fd, 'r+b')
        try:
            if not stat.S_ISREG(os.fstat(self.file.fileno()).st_mode):
                raise DownloadError('Partial download must be a regular file')
            try:
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DownloadBusy(spec.filename + ' is already being downloaded by another NFSMW Builder window '
                                   'or build. Wait for it to finish, then try again.') from None
            self.digest, self.kept = hashlib.sha256(), os.fstat(self.file.fileno()).st_size
            if self.kept > spec.size:
                self.reset()
            while chunk := self.file.read(min(BLOCK_BYTES, self.kept - self.file.tell())):
                self.digest.update(chunk)
            if self.file.tell() != self.kept:
                raise DownloadError('Partial download changed while it was checked')
        except BaseException:
            self.file.close()
            raise

    def complete(self):
        return self.kept == self.spec.size and self.digest.hexdigest() == self.spec.sha256

    def rewind(self):
        """Drop anything written after the last counted byte."""
        self.file.seek(self.kept)
        self.file.truncate(self.kept)

    def reset(self):
        self.file.seek(0)
        self.file.truncate(0)
        self.digest, self.kept = hashlib.sha256(), 0

    def append(self, chunk):
        self.file.write(chunk)
        self.digest.update(chunk)
        self.kept += len(chunk)

    def close(self):
        self.file.close()


def _publish_partial(partial, spec, cache, directory, original, report):
    partial.file.flush()
    os.fsync(partial.file.fileno())
    result = _publish(partial.name, spec, cache, directory, original)
    _unlink(partial.name, directory)
    report(spec.size, final=True)
    return result


def _resumable(client, candidate, spec, cache, directory, original, progress, partial):
    """Continue the kept partial file with an HTTP Range request; the pin still decides."""
    url, headers, timeout = candidate
    report = _Progress(progress, spec.size)
    partial.rewind()
    if partial.kept == spec.size:
        partial.reset()  # complete but wrong; fetch_patch publishes a complete and right one
    report(partial.kept)
    kept = partial.kept
    request = dict(headers, Range=f'bytes={kept}-') if kept else headers
    try:
        response = _open(client, url, request, timeout, statuses=(200, 206))
    except RangeRefused:
        partial.reset()
        raise
    with response:
        if response.status == 206:
            if response.headers.get('Content-Range') != f'bytes {kept}-{spec.size - 1}/{spec.size}':
                partial.reset()
                raise DownloadError('Response does not continue the partial download')
            _check_headers(response, spec.size - kept)
        else:
            _check_headers(response, spec.size)
            partial.reset()
        deadline = time.monotonic() + STALL_SECONDS
        while chunk := _read(response, min(BLOCK_BYTES, spec.size - partial.kept + 1), deadline):
            if partial.kept + len(chunk) > spec.size:
                partial.reset()
                raise DownloadError('Response exceeds the pinned payload size')
            partial.append(chunk)
            deadline = time.monotonic() + STALL_SECONDS
            report(partial.kept)
        partial.file.flush()
        if partial.kept != spec.size:
            raise DownloadError('Download stopped before the end; the partial file is kept')
        if not partial.complete():
            partial.reset()
            raise DownloadError('Payload size or SHA-256 does not match its pin')
    return _publish_partial(partial, spec, cache, directory, original, report)


def partial_bytes(key, cache=Path('out/downloads')) -> int:
    """Bytes kept from an interrupted large download, 0 when there are none. Never creates anything."""
    try:
        info = os.lstat(Path(cache) / _partial_name(SOURCES[key]))
    except FileNotFoundError:
        return 0
    return info.st_size if stat.S_ISREG(info.st_mode) else 0


def verify_patch(key, path) -> Path:
    """Verify a supplied payload without network or writes; official means EXE."""
    if key not in SOURCES:
        raise ValueError('Unknown patch source key')
    path = Path(os.path.abspath(path))
    try:
        _directory(path.parent, create=False)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if not _verified(SOURCES[key], directory, _state(path.name, directory), path.name):
                raise ValueError('Payload size or SHA-256 does not match ' + key)
        finally:
            os.close(directory)
    except (OSError, DownloadError):
        raise ValueError('Payload is missing, unsafe or changed during verification') from None
    return path


def import_patch(key, source, cache=Path('out/downloads')) -> Path:
    """Copy a payload the user already has into the cache after verifying it twice.

    The source is only read: it is never moved, renamed, changed or written next to.
    """
    source = verify_patch(key, source)
    spec = SOURCES[key]
    cache = _directory(cache)
    directory = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = '.' + spec.filename + '.' + secrets.token_hex(8) + '.import'
    try:
        original = _state(spec.filename, directory)
        if _verified(spec, directory, original):
            return cache / spec.filename
        target = cache / temporary
        # An APFS clone is instant and takes no space; other volumes get a plain copy.
        if subprocess.run(['/bin/cp', '-c', str(source), str(target)], capture_output=True).returncode:
            _unlink(temporary, directory)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with source.open('rb') as reader, os.fdopen(fd, 'wb') as writer:
                shutil.copyfileobj(reader, writer, BLOCK_BYTES)
        if not _verified(spec, directory, _state(temporary, directory), temporary):
            raise ValueError('Payload size or SHA-256 does not match ' + key)
        result = _publish(temporary, spec, cache, directory, original)
        if spec.size >= RESUMABLE_BYTES:
            _unlink(_partial_name(spec), directory)
        return result
    finally:
        _unlink(temporary, directory)
        os.close(directory)


def fetch_patch(key, cache=Path('out/downloads'), progress=None) -> Path:
    """Return a fully verified payload; EXE files are downloaded, never executed.

    progress(received, total) is called at most every PROGRESS_SECONDS and once at the end.
    Large payloads keep a partial file in the cache and continue it on the next call.
    """
    if key not in SOURCES:
        raise ValueError('Unknown patch source key')
    spec = SOURCES[key]
    cache = _directory(cache)
    directory = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        original = _state(spec.filename, directory)
        if _verified(spec, directory, original):
            if progress:
                progress(spec.size, spec.size)
            return cache / spec.filename
        # No browser state, persisted cookie store, proxy credentials or URL log.
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}), HTTPSRedirect(),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        headers = {'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'}
        if spec.kind == 'github':
            headers['Accept'] = 'application/octet-stream'
        partial = _Partial(spec, directory) if spec.size >= RESUMABLE_BYTES else None
        try:
            if partial is not None and partial.complete():
                return _publish_partial(partial, spec, cache, directory, original, _Progress(progress, spec.size))
            for candidate in _candidates(key, spec, client, headers):
                try:
                    return _download(client, candidate, spec, cache, directory, original, progress, partial)
                except _FAILURES as error:
                    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
                        raise DiskFull('Not enough free space to download ' + spec.filename) from None
                    continue
        finally:
            if partial is not None:
                partial.close()
        raise DownloadError('No verified download available for ' + key) from None
    finally:
        os.close(directory)
