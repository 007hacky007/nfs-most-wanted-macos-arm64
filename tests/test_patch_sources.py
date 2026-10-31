"""Fake HTTP at the opener boundary; exercise real streaming and cache files."""
from dataclasses import replace
import hashlib
import http.cookiejar
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from tools import patch_sources as subject

PAYLOAD = b'verified synthetic archive payload'

class Response(io.BytesIO):
    def __init__(self, body, *, url='https://downloads.example.test/payload', headers=None, status=200, on_read=None, broken=False):
        super().__init__(body)
        self.headers = {} if headers is None else headers
        self.status, self.url, self.on_read, self.broken = status, url, on_read, broken
        self.reads = 0
    def read1(self, count=-1):
        return self.read(count)
    def geturl(self):
        return self.url
    def read(self, count=-1):
        if self.on_read:
            action, self.on_read = self.on_read, None
            action()
        self.reads += 1
        if self.broken and self.reads > 1:
            raise OSError('failed signed secret-token URL')
        return super().read(min(count, 3) if self.broken else count)

class Client:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if not self.replies:
            raise AssertionError('unexpected HTTP request')
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

class PatchSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cache = self.root / 'cache'
        self.specs = {key: replace(value, size=len(PAYLOAD), sha256=hashlib.sha256(PAYLOAD).hexdigest())
                      for key, value in subject.SOURCES.items()}
        self.mapping = patch.dict(subject.SOURCES, self.specs)
        self.mapping.start()
        self.addCleanup(self.mapping.stop)
    def fetch(self, key, replies, cache=None):
        client = Client(replies)
        with patch.object(subject.urllib.request, 'build_opener', return_value=client):
            result = subject.fetch_patch(key, cache or self.cache)
        return result, client
    def entries(self):
        return sorted(path.name for path in self.cache.iterdir()) if self.cache.exists() else []
    def test_stream_hash_atomic_publication_and_verified_cache_hit(self):
        destination = self.cache / self.specs['directx'].filename
        reply = Response(PAYLOAD, on_read=lambda: self.assertFalse(destination.exists()))
        result, client = self.fetch('directx', [reply])
        self.assertEqual(result, destination)
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertEqual(self.entries(), [destination.name])
        self.assertTrue(reply.closed)
        again, cached = self.fetch('directx', [])
        self.assertEqual(again, result)
        self.assertFalse(cached.calls)
        self.assertEqual(client.calls[0][0].get_header('User-agent'), 'NFSMW-native-build')
        self.assertIsNone(client.calls[0][0].get_header('Authorization'))
    def test_cache_contents_are_rehashed_and_corrupt_regular_file_replaced(self):
        destination, _ = self.fetch('directx', [Response(PAYLOAD)])
        destination.write_bytes(b'x' * len(PAYLOAD))
        result, client = self.fetch('directx', [Response(PAYLOAD)])
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertEqual(len(client.calls), 1)
    def test_failed_download_preserves_previous_file_and_cleans_partials(self):
        self.cache.mkdir()
        destination = self.cache / self.specs['directx'].filename
        destination.write_bytes(b'old corrupt cache')
        for reply in (Response(b'x' * len(PAYLOAD)), Response(PAYLOAD[:-1]), Response(PAYLOAD + b'overflow'), Response(PAYLOAD, broken=True)):
            with self.subTest(kind=repr(reply)):
                with self.assertRaises(subject.DownloadError) as failure:
                    self.fetch('directx', [reply])
                self.assertNotIn('secret-token', str(failure.exception))
                self.assertEqual(destination.read_bytes(), b'old corrupt cache')
                self.assertEqual(self.entries(), [destination.name])
                self.assertTrue(reply.closed)
    def test_invalid_http_metadata_and_non_https_final_response_rejected(self):
        replies = [Response(PAYLOAD, headers={'Content-Length': '1'}), Response(PAYLOAD, status=206),
                   Response(PAYLOAD, headers={'Content-Encoding': 'gzip'}), Response(PAYLOAD, url='http://example.test/payload')]
        for reply in replies:
            with self.subTest(headers=reply.headers, status=reply.status, url=reply.url):
                with self.assertRaises(subject.DownloadError):
                    self.fetch('directx', [reply])
                self.assertFalse(self.entries())
    def test_symlink_payload_and_cache_parent_are_preserved(self):
        outside = self.root / 'outside'
        outside.write_bytes(b'untouched')
        self.cache.mkdir()
        destination = self.cache / self.specs['directx'].filename
        destination.symlink_to(outside)
        with self.assertRaises(subject.DownloadError):
            self.fetch('directx', [])
        self.assertTrue(destination.is_symlink())
        self.assertEqual(outside.read_bytes(), b'untouched')
        alias = self.root / 'alias'
        alias.symlink_to(self.cache, target_is_directory=True)
        with self.assertRaises(subject.DownloadError):
            self.fetch('directx', [], alias / 'nested')
        self.assertFalse((self.cache / 'nested').exists())
    def test_symlink_or_regular_file_appearing_during_stream_is_not_replaced(self):
        self.cache.mkdir()
        destination = self.cache / self.specs['directx'].filename
        outside = self.root / 'outside'
        outside.write_bytes(b'untouched')
        for symlink in (True, False):
            def insert():
                if symlink:
                    destination.symlink_to(outside)
                else:
                    destination.write_bytes(b'concurrent owner')
            with self.subTest(symlink=symlink):
                with self.assertRaises(subject.DownloadError):
                    self.fetch('directx', [Response(PAYLOAD, on_read=insert)])
                self.assertEqual(destination.is_symlink(), symlink)
                self.assertEqual(destination.read_bytes(), b'untouched' if symlink else b'concurrent owner')
                self.assertEqual(self.entries(), [destination.name])
                destination.unlink()
    def test_ea_timeout_falls_back_only_to_approved_checksum_mirror(self):
        result, client = self.fetch('official-1.3', [TimeoutError(), Response(PAYLOAD)])
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertEqual([call[0].full_url for call in client.calls], list(self.specs['official-1.3'].urls))
        self.assertLessEqual(client.calls[0][1], 8)
        self.assertIn('nfsplanet.com', client.calls[1][0].full_url)
    def test_github_uses_pinned_asset_endpoint_and_octet_stream(self):
        _, client = self.fetch('widescreen', [Response(PAYLOAD)])
        request = client.calls[0][0]
        self.assertEqual(request.full_url, 'https://api.github.com/repos/ThirteenAG/WidescreenFixesPack/releases/assets/558912001')
        self.assertEqual(request.get_header('Accept'), 'application/octet-stream')
    def test_hq_discovers_start_then_all_with_fresh_anonymous_cookie_jar(self):
        start = self.specs['mw-hq'].urls[0]
        bad = '<a href="https://elsewhere.test/downloads/mirror/233611/1/private">bad</a>'
        first = '<a href="/downloads/mirror/233611/130/temporary-one">first</a>'
        second = '<a href="/downloads/mirror/233611/135/temporary-two?a=1&amp;b=2">second</a>'
        clients, jars = [], []
        def opener(*handlers):
            jars.extend(handler.cookiejar for handler in handlers if hasattr(handler, 'cookiejar'))
            client = Client([Response((bad + first).encode()), OSError('temporary-one'), Response(second.encode()),
                             Response(PAYLOAD, url='https://cdn.dbolical.com/archive?secret-token=temporary')])
            clients.append(client)
            return client
        with patch.object(subject.urllib.request, 'build_opener', side_effect=opener):
            for number in range(2):
                result = subject.fetch_patch('mw-hq', self.root / ('hq' + str(number)))
                self.assertEqual(result.read_bytes(), PAYLOAD)
                self.assertEqual([p.name for p in result.parent.iterdir()], [self.specs['mw-hq'].filename])
        self.assertEqual(len(jars), 2)
        self.assertIsNot(jars[0], jars[1])
        self.assertTrue(all(isinstance(jar, http.cookiejar.CookieJar) for jar in jars))
        for client in clients:
            urls = [call[0].full_url for call in client.calls]
            self.assertEqual(urls[0], start)
            self.assertEqual(urls[2], start + '/all')
            self.assertTrue(urls[3].endswith('temporary-two?a=1&b=2'))
            self.assertEqual(client.calls[3][0].get_header('Referer'), start + '/all')
    def test_hq_bad_checksum_tries_next_fresh_candidate(self):
        listing = '<a href="/downloads/mirror/233611/1/one">1</a><a href="/downloads/mirror/233611/2/two">2</a>'
        result, client = self.fetch('mw-hq', [Response(listing.encode()), Response(b'x' * len(PAYLOAD)), Response(PAYLOAD)])
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(self.entries(), [result.name])
    def test_discovery_pages_are_bounded_and_failure_hides_temporary_tokens(self):
        with patch.object(subject, 'MAX_LISTING_BYTES', 16):
            with self.assertRaises(subject.DownloadError) as failure:
                self.fetch('mw-hq', [Response(b'x' * 17), urllib.error.URLError('secret-token')])
        self.assertNotIn('secret-token', str(failure.exception))
        self.assertFalse(self.entries())
    def test_malformed_mirror_link_does_not_hide_a_later_valid_candidate(self):
        page = b'<a href="https://[">bad</a><a href="/downloads/mirror/233611/1/ok">ok</a>'
        result, client = self.fetch('mw-hq', [Response(page), Response(PAYLOAD)])
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertEqual(len(client.calls), 2)
    def test_origin_transfer_deadline_falls_back_without_publishing_late_data(self):
        clock = [0.0]
        def slow():
            clock[0] = 21.0
        origin = Response(PAYLOAD, on_read=slow)
        with patch.object(subject.time, 'monotonic', side_effect=lambda: clock[0]):
            result, client = self.fetch('official-1.3', [origin, Response(PAYLOAD)])
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(origin.closed)
    def test_cancellation_closes_response_and_removes_partial_payload(self):
        def cancel():
            raise KeyboardInterrupt()
        reply = Response(PAYLOAD, on_read=cancel)
        with self.assertRaises(KeyboardInterrupt):
            self.fetch('directx', [reply])
        self.assertTrue(reply.closed)
        self.assertFalse(self.entries())

    def test_redirect_handler_refuses_downgrades(self):
        handler = subject.HTTPSRedirect()
        request = subject.urllib.request.Request('https://example.test/file')
        with self.assertRaises(subject.DownloadError):
            handler.redirect_request(request, None, 302, 'redirect', {}, 'http://example.test/file')
    def test_provided_payload_verification_needs_no_network_or_fixed_basename(self):
        supplied = self.root / 'chosen-name.zip'
        supplied.write_bytes(PAYLOAD)
        with patch.object(subject.urllib.request, 'build_opener', side_effect=AssertionError('no network')):
            self.assertEqual(subject.verify_patch('widescreen', supplied), supplied)
            supplied.write_bytes(b'x' * len(PAYLOAD))
            with self.assertRaises(ValueError):
                subject.verify_patch('widescreen', supplied)
            supplied.write_bytes(PAYLOAD[:-1])
            with self.assertRaises(ValueError):
                subject.verify_patch('widescreen', supplied)
    def test_provided_missing_nonregular_and_symlink_are_rejected_without_creation(self):
        supplied = self.root / 'original'
        supplied.write_bytes(PAYLOAD)
        alias = self.root / 'alias'
        alias.symlink_to(supplied)
        missing = self.root / 'absent' / 'file'
        for candidate in (alias, self.root, missing):
            with self.subTest(candidate=candidate.name), self.assertRaises(ValueError):
                subject.verify_patch('mw-hq', candidate)
        self.assertFalse(missing.parent.exists())
        self.assertEqual(supplied.read_bytes(), PAYLOAD)
    def test_cache_directory_replacement_cannot_redirect_publication(self):
        self.cache.mkdir()
        moved = self.root / 'moved'
        outside = self.root / 'outside'
        outside.mkdir()
        def redirect():
            self.cache.rename(moved)
            self.cache.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(subject.DownloadError):
            self.fetch('directx', [Response(PAYLOAD, on_read=redirect)])
        self.assertFalse(list(outside.iterdir()))
        self.assertFalse(list(moved.iterdir()))
    def test_mirror_candidates_have_a_finite_attempt_limit(self):
        listing = ''.join('<a href="/downloads/mirror/233611/%d/token">mirror</a>' % n for n in range(30))
        replies = [Response(listing.encode())] + [OSError('offline')] * 3
        with patch.object(subject, 'MAX_MIRRORS', 3):
            with self.assertRaises(subject.DownloadError):
                self.fetch('mw-hq', replies)

    def large(self):
        limit = patch.object(subject, 'RESUMABLE_BYTES', 4)
        limit.start()
        self.addCleanup(limit.stop)
        return self.cache / ('.' + self.specs['directx'].filename + '.partial')

    def ranged(self, start, body=None):
        size = len(PAYLOAD)
        body = PAYLOAD[start:] if body is None else body
        return Response(body, status=206, headers={'Content-Range': f'bytes {start}-{size - 1}/{size}',
                                                   'Content-Length': str(len(body))})

    def test_large_download_resumes_with_range_after_drop(self):
        partial = self.large()
        with self.assertRaises(subject.DownloadError):
            self.fetch('directx', [Response(PAYLOAD, broken=True)])
        self.assertEqual(partial.read_bytes(), PAYLOAD[:3])
        self.assertEqual(partial.stat().st_mode & 0o777, 0o600)
        self.assertEqual(subject.partial_bytes('directx', self.cache), 3)
        self.assertEqual(self.entries(), [partial.name])
        result, client = self.fetch('directx', [self.ranged(3)])
        self.assertEqual(client.calls[0][0].get_header('Range'), 'bytes=3-')
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertEqual(self.entries(), [result.name])
        self.assertEqual(subject.partial_bytes('directx', self.cache), 0)

    def test_resume_restarts_on_200_and_discards_on_bad_content_range(self):
        partial = self.large()
        self.cache.mkdir()
        partial.write_bytes(b'xyz')
        result, client = self.fetch('directx', [Response(PAYLOAD)])
        self.assertEqual(client.calls[0][0].get_header('Range'), 'bytes=3-')
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertFalse(partial.exists())
        result.unlink()
        partial.write_bytes(PAYLOAD[:3])
        bad = self.ranged(3)
        bad.headers['Content-Range'] = 'bytes 0-2/3'
        with self.assertRaises(subject.DownloadError):
            self.fetch('directx', [bad])
        self.assertEqual(subject.partial_bytes('directx', self.cache), 0)
        self.assertNotIn(result.name, self.entries())
        refused = urllib.error.HTTPError('https://example.test', 416, 'range', {}, io.BytesIO())
        partial.write_bytes(PAYLOAD[:3])
        with self.assertRaises(subject.DownloadError):
            self.fetch('directx', [refused])
        self.assertEqual(subject.partial_bytes('directx', self.cache), 0)

    def test_complete_partial_is_published_without_network(self):
        partial = self.large()
        self.cache.mkdir()
        partial.write_bytes(PAYLOAD)
        result, client = self.fetch('directx', [])
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertEqual(client.calls, [])
        self.assertEqual(self.entries(), [result.name])
        result.unlink()
        partial.write_bytes(b'x' * len(PAYLOAD))
        result, client = self.fetch('directx', [Response(PAYLOAD)])
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertIsNone(client.calls[0][0].get_header('Range'))

    def test_partial_is_hashed_once_per_fetch(self):
        self.large()
        self.cache.mkdir()
        partial = self.cache / ('.' + self.specs['official-1.3'].filename + '.partial')
        partial.write_bytes(PAYLOAD[:3])
        reads = []
        real = subject._Partial.__init__
        def counting(inner, *args):
            reads.append(1)
            real(inner, *args)
        with patch.object(subject._Partial, '__init__', counting):
            result, client = self.fetch('official-1.3', [OSError('first source'), self.ranged(3)])
        self.assertEqual(len(reads), 1)
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertEqual([c[0].get_header('Range') for c in client.calls], ['bytes=3-', 'bytes=3-'])

    def test_full_disk_stops_at_once_and_keeps_the_partial(self):
        import errno
        self.large()
        self.cache.mkdir()
        partial = self.cache / ('.' + self.specs['official-1.3'].filename + '.partial')
        partial.write_bytes(PAYLOAD[:3])
        with patch.object(subject._Partial, 'append', side_effect=OSError(errno.ENOSPC, 'No space left on device')):
            with self.assertRaises(subject.DiskFull):
                _, client = self.fetch('official-1.3', [self.ranged(3), AssertionError('no second mirror')])
        self.assertEqual(partial.read_bytes(), PAYLOAD[:3])
        small = Response(PAYLOAD)
        with patch.object(subject.os, 'fsync', side_effect=OSError(errno.ENOSPC, 'No space left on device')):
            with self.assertRaises(subject.DiskFull):
                self.fetch('widescreen', [small])
        self.assertNotIn(self.specs['widescreen'].filename, self.entries())

    def test_locked_partial_fails_before_any_request(self):
        import fcntl
        partial = self.large()
        self.cache.mkdir()
        partial.write_bytes(PAYLOAD[:3])
        with partial.open('r+b') as other:
            fcntl.flock(other.fileno(), fcntl.LOCK_EX)
            with self.assertRaises(subject.DownloadBusy) as failure:
                self.fetch('directx', [])
        self.assertIn('already being downloaded', str(failure.exception))
        self.assertEqual(partial.read_bytes(), PAYLOAD[:3])

    def test_wrong_final_hash_never_publishes_and_drops_partial(self):
        partial = self.large()
        self.cache.mkdir()
        partial.write_bytes(PAYLOAD[:3])
        with self.assertRaises(subject.DownloadError):
            self.fetch('directx', [self.ranged(3, b'x' * (len(PAYLOAD) - 3))])
        self.assertEqual(self.entries(), [partial.name])
        self.assertEqual(partial.stat().st_size, 0)

    def test_stall_timeout_not_total_budget_for_large_files(self):
        partial = self.large()
        clock = [0.0]
        class Slow(Response):
            def read(inner, count=-1):
                clock[0] += next(inner.steps, inner.last)
                return io.BytesIO.read(inner, min(count, 3))
        steady = Slow(PAYLOAD)
        steady.steps, steady.last = iter(()), 100.0
        with patch.object(subject.time, 'monotonic', side_effect=lambda: clock[0]):
            result, _ = self.fetch('directx', [steady])
            self.assertGreater(clock[0], 1000)
            self.assertEqual(result.read_bytes(), PAYLOAD)
            result.unlink()
            stalled = Slow(PAYLOAD)
            stalled.steps, stalled.last = iter((1.0,)), 121.0
            with self.assertRaises(subject.DownloadError):
                self.fetch('directx', [stalled])
        self.assertEqual(partial.read_bytes(), PAYLOAD[:3])

    def test_progress_callback_reports_bytes(self):
        for large in (False, True):
            with self.subTest(large=large):
                if large:
                    self.large()
                seen = []
                client = Client([Response(PAYLOAD)])
                cache = self.root / f'progress-{large}'
                with patch.object(subject.urllib.request, 'build_opener', return_value=client):
                    subject.fetch_patch('directx', cache, progress=lambda got, total: seen.append((got, total)))
                self.assertEqual(seen[-1], (len(PAYLOAD), len(PAYLOAD)))
                self.assertEqual([got for got, _ in seen], sorted(got for got, _ in seen))
                again = []
                subject.fetch_patch('directx', cache, progress=lambda got, total: again.append(got))
                self.assertEqual(again, [len(PAYLOAD)])

    def test_import_verifies_copies_and_leaves_source_untouched(self):
        folder = self.root / 'chosen'
        folder.mkdir()
        source = folder / 'My download.zip'
        source.write_bytes(PAYLOAD)
        wrong = folder / 'wrong.zip'
        wrong.write_bytes(b'x' * len(PAYLOAD))
        folder.chmod(0o555)
        self.addCleanup(folder.chmod, 0o755)
        before = [(p.name, p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ino) for p in sorted(folder.iterdir())]
        with self.assertRaises(ValueError):
            subject.import_patch('widescreen', wrong, self.cache)
        self.assertEqual(self.entries(), [])
        with patch.object(subject.urllib.request, 'build_opener', side_effect=AssertionError('no network')):
            result = subject.import_patch('widescreen', source, self.cache)
        self.assertEqual(result, self.cache / self.specs['widescreen'].filename)
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertNotEqual(result.stat().st_ino, source.stat().st_ino)
        self.assertEqual(self.entries(), [result.name])
        after = [(p.name, p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ino) for p in sorted(folder.iterdir())]
        self.assertEqual(after, before)

    def test_import_falls_back_to_a_plain_copy_and_removes_partial(self):
        partial = self.large()
        self.cache.mkdir()
        partial.write_bytes(b'abc')
        source = self.root / 'file'
        source.write_bytes(PAYLOAD)
        failed = subject.subprocess.CompletedProcess(['cp'], 1, b'', b'')
        with patch.object(subject.subprocess, 'run', return_value=failed):
            result = subject.import_patch('directx', source, self.cache)
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertEqual(self.entries(), [result.name])

    def test_unknown_key_has_no_filesystem_or_network_effect(self):
        with self.assertRaises(ValueError):
            self.fetch('../unknown', [])
        self.assertFalse(self.cache.exists())

if __name__ == '__main__':
    unittest.main()
