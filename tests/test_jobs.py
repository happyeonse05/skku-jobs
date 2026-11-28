import contextlib
import datetime
import io
import json
import pathlib
import runpy
import stat
import tempfile
import unittest
from unittest import mock

from crawler import jobs


class JobsSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = pathlib.Path(self.directory.name) / 'jobs.json'
        self.before = b'{"updated":"old-complete-run","items":[{"id":"keep-both-boards"}]}\n'
        self.path.write_bytes(self.before)
        self.path.chmod(0o644)
        self.boards = [('jobs', 'https://fixture.invalid/jobs'),
                       ('scholarships', 'https://fixture.invalid/scholarships')]
        self.enterContext(mock.patch.object(jobs, 'OUT', self.path))
        self.enterContext(mock.patch.object(jobs, 'BOARDS', self.boards))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        # Unexpected real HTTP is a test failure, never an operating crawl.
        self.enterContext(mock.patch('requests.sessions.Session.request',
                                    side_effect=AssertionError('external request blocked')))

    def run_results(self, results):
        with mock.patch.object(jobs, 'crawl_board', side_effect=results) as crawl:
            result = jobs.main()
        self.assertEqual(crawl.call_count, 2)
        return result

    def assert_preserved(self):
        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertEqual(list(self.path.parent.glob('.*.tmp')), [])

    def test_partial_network_failure_preserves_complete_feed(self):
        for results in [[OSError('timeout'), [{'id': 'new'}]],
                        [[{'id': 'new'}], OSError('timeout')]]:
            with self.subTest(results=results):
                self.path.write_bytes(self.before)
                self.assertIs(self.run_results(results), False)
                self.assert_preserved()

    def test_empty_board_preserves_complete_feed(self):
        for results in [[[], [{'id': 'new'}]], [[{'id': 'new'}], []]]:
            with self.subTest(results=results):
                self.path.write_bytes(self.before)
                self.assertIs(self.run_results(results), False)
                self.assert_preserved()

    def test_all_failed_preserves_original_timestamp_and_bytes(self):
        self.assertIs(self.run_results([OSError('offline'), OSError('offline')]), False)
        self.assert_preserved()

    def test_failed_first_run_does_not_publish_empty_feed(self):
        self.path.unlink()
        self.assertIs(self.run_results([OSError('offline'), OSError('offline')]), False)
        self.assertFalse(self.path.exists())

    def test_empty_first_run_does_not_publish_empty_feed(self):
        self.path.unlink()
        self.assertIs(self.run_results([[], []]), False)
        self.assertFalse(self.path.exists())

    def test_no_configured_boards_preserves_feed(self):
        with mock.patch.object(jobs, 'BOARDS', []):
            self.assertIs(jobs.main(), False)
        self.assert_preserved()

    def test_complete_snapshot_replaces_old_feed_with_existing_limit(self):
        items = [{'id': str(n), 'title': '합성 공지'} for n in range(65)]
        self.assertIs(self.run_results([items[:30], items[30:]]), True)
        payload = json.loads(self.path.read_text())
        self.assertEqual(set(payload), {'updated', 'items'})
        self.assertEqual(payload['items'], items[:60])
        self.assertEqual(datetime.datetime.fromisoformat(payload['updated']).utcoffset(),
                         datetime.timedelta(hours=9))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)

    def test_http_parse_to_saved_consumer_schema(self):
        def response(article, title):
            r = mock.Mock()
            r.text = f'<ul><li><a href="?articleNo={article}">{title}</a><span>2026.11.24</span></li></ul>'
            return r
        with mock.patch.object(jobs.requests, 'get', side_effect=[
            response(1, '합성 채용 안내'), response(2, '합성 장학 안내')]):
            self.assertIs(jobs.main(), True)
        items = json.loads(self.path.read_text())['items']
        self.assertEqual([i['writer'] for i in items], ['jobs', 'scholarships'])
        self.assertEqual([i['posted'] for i in items], ['2026-11-24'] * 2)
        self.assertTrue(all(len(i['id']) == 12 and i['url'].startswith('https://fixture.invalid/')
                            for i in items))

    def test_http_success_page_without_articles_is_not_complete(self):
        good = mock.Mock(text='<li><a href="?articleNo=1">합성 채용 모집 안내</a></li>')
        maintenance = mock.Mock(text='<html><h1>maintenance</h1></html>')
        with mock.patch.object(jobs.requests, 'get', side_effect=[good, maintenance]):
            self.assertIs(jobs.main(), False)
        self.assert_preserved()

    def test_recovery_after_failure_publishes_complete_snapshot(self):
        self.run_results([[{'id': 'partial'}], OSError('offline')])
        self.assert_preserved()
        self.assertIs(self.run_results([[{'id': 'a'}], [{'id': 'b'}]]), True)
        self.assertEqual([i['id'] for i in json.loads(self.path.read_text())['items']], ['a', 'b'])

    def test_replace_failure_preserves_old_file_and_removes_temporary(self):
        with mock.patch.object(jobs.os, 'replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.run_results([[{'id': 'a'}], [{'id': 'b'}]])
        self.assert_preserved()

    def test_fsync_failure_preserves_old_file_and_removes_temporary(self):
        with mock.patch.object(jobs.os, 'fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.run_results([[{'id': 'a'}], [{'id': 'b'}]])
        self.assert_preserved()

    def test_serialization_failure_never_truncates_old_file(self):
        with self.assertRaises(TypeError):
            jobs.write_snapshot(self.path, {'items': ['valid', object()]})
        self.assert_preserved()

    def test_reader_sees_old_complete_file_until_replace(self):
        replace = jobs.os.replace
        def observe(source, destination):
            self.assertEqual(self.path.read_bytes(), self.before)
            self.assertEqual(json.loads(pathlib.Path(source).read_text())['items'], ['new'])
            self.assertEqual(pathlib.Path(source).parent, self.path.parent)
            return replace(source, destination)
        with mock.patch.object(jobs.os, 'replace', side_effect=observe):
            jobs.write_snapshot(self.path, {'updated': 'new', 'items': ['new']})
        self.assertEqual(json.loads(self.path.read_text())['items'], ['new'])

    def test_successful_first_run_creates_parent_directory(self):
        nested = self.path.parent / 'nested' / 'jobs.json'
        with mock.patch.object(jobs, 'OUT', nested):
            self.assertIs(self.run_results([[{'id': 'a'}], [{'id': 'b'}]]), True)
        self.assertEqual(len(json.loads(nested.read_text())['items']), 2)

    def test_cli_reports_incomplete_crawl_as_failure(self):
        with mock.patch.object(jobs.requests, 'get', side_effect=OSError('synthetic offline')):
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(pathlib.Path(jobs.__file__)), run_name='__main__')
        self.assertEqual(result.exception.code, 1)


if __name__ == '__main__':
    unittest.main()
