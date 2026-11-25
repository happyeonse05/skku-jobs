import contextlib
import datetime
import io
import json
import pathlib
import runpy
import stat
import tempfile
import types
import unittest
from unittest import mock

from crawler import meals

TODAY = datetime.date(2026, 11, 25)
START = datetime.date(2026, 11, 23)
COUNT = 10
HTML = '<div>신관</div><p>07:00~09:00</p><p>밥, 국, 밥, *6000*</p><div>Take-out</div><p>12:00~14:00</p><p>합성 샌드위치</p><div>신관</div><p>17:00~19:00</p><p>합성 저녁국</p>'


class MealsSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = pathlib.Path(self.directory.name) / 'data' / 'meals.json'
        self.path.parent.mkdir()
        self.before = b'{"updated":"old-synthetic","days":{"2026-11-25":{"lunch":["keep"]}}}\n'
        self.path.write_bytes(self.before)
        self.path.chmod(0o640)
        self.mtime = self.path.stat().st_mtime_ns
        self.enterContext(mock.patch.object(meals, 'OUT', self.path))
        self.enterContext(mock.patch.object(meals, 'TODAY', TODAY))
        self.enterContext(mock.patch.object(meals.time, 'sleep'))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(mock.patch('requests.sessions.Session.request', side_effect=AssertionError('external request blocked')))

    def results(self, values):
        with mock.patch.object(meals, 'crawl_day', side_effect=values) as crawl:
            result = meals.main()
        self.assertEqual(crawl.call_count, COUNT)
        self.assertEqual(crawl.call_args_list[0].args, (START,))
        self.assertEqual(crawl.call_args_list[-1].args, (TODAY + datetime.timedelta(days=7),))
        return result

    def complete(self):
        return [{'lunch': ['합성 새 점심'], 'dinner': ['합성 저녁']} for _ in range(COUNT)]

    def preserved(self):
        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertEqual(self.path.stat().st_mtime_ns, self.mtime)
        self.assertEqual(list(self.path.parent.glob('.*.tmp')), [])

    def test_any_failed_date_preserves_complete_feed_bytes_and_timestamp(self):
        for index in [0, COUNT // 2, COUNT - 1]:
            with self.subTest(index=index):
                values = self.complete(); values[index] = OSError('synthetic timeout')
                self.assertIs(self.results(values), False)
                self.preserved()

    def test_all_failed_dates_preserve_existing_feed(self):
        self.assertIs(self.results([OSError('synthetic offline')] * COUNT), False)
        self.preserved()

    def test_all_empty_dates_preserve_existing_feed(self):
        self.assertIs(self.results([{} for _ in range(COUNT)]), False)
        self.preserved()

    def test_incomplete_or_empty_first_run_publishes_nothing(self):
        self.path.unlink()
        for values in [[OSError('offline')] * COUNT, [{} for _ in range(COUNT)], [OSError('offline')] + self.complete()[1:]]:
            with self.subTest(values=bool(values[0])):
                self.assertIs(self.results(values), False)
                self.assertFalse(self.path.exists())
                self.assertEqual(list(self.path.parent.glob('.*.tmp')), [])

    def test_complete_crawl_publishes_all_dates_with_existing_schema(self):
        self.assertIs(self.results(self.complete()), True)
        value = json.loads(self.path.read_text())
        self.assertEqual(set(value), {'updated', 'days'})
        self.assertEqual(len(value['days']), COUNT)
        self.assertEqual(value['days'][TODAY.isoformat()]['lunch'], ['합성 새 점심'])
        self.assertEqual(datetime.datetime.fromisoformat(value['updated']).utcoffset(), datetime.timedelta(hours=9))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)

    def test_legitimate_closed_date_is_allowed_when_other_dates_have_menus(self):
        values = self.complete(); values[(TODAY - START).days] = {}
        self.assertIs(self.results(values), True)
        value = json.loads(self.path.read_text())
        self.assertNotIn(TODAY.isoformat(), value['days'])
        self.assertEqual(len(value['days']), COUNT - 1)

    def test_retry_after_partial_failure_can_publish_complete_feed(self):
        self.assertIs(self.results([OSError('offline')] + self.complete()[1:]), False)
        self.preserved()
        self.assertIs(self.results(self.complete()), True)
        self.assertEqual(len(json.loads(self.path.read_text())['days']), COUNT)

    def test_actual_html_parser_still_handles_meal_types_and_utf8(self):
        response = types.SimpleNamespace(text=HTML, apparent_encoding='utf-8', encoding=None, raise_for_status=mock.Mock())
        with mock.patch.object(meals.requests, 'get', return_value=response) as get:
            result = meals.crawl_day(TODAY)
        self.assertEqual(result, {'breakfast': ['밥', '국'], 'lunch': ['합성 샌드위치'], 'dinner': ['합성 저녁국']})
        self.assertEqual(get.call_args.kwargs['params']['date'], TODAY.isoformat())
        self.assertEqual(get.call_args.kwargs['timeout'], 20)
        response.raise_for_status.assert_called_once()

    def test_http_error_is_not_a_closed_date(self):
        response = types.SimpleNamespace(raise_for_status=mock.Mock(side_effect=OSError('synthetic 503')))
        with mock.patch.object(meals.requests, 'get', return_value=response):
            with self.assertRaises(OSError): meals.crawl_day(TODAY)

    def test_serialization_failure_never_truncates_feed(self):
        with self.assertRaises(TypeError): meals.write_snapshot(self.path, {'days': ['valid', object()]})
        self.preserved()

    def test_fsync_failure_cleans_temporary_and_preserves_feed(self):
        with mock.patch.object(meals.os, 'fsync', side_effect=OSError('synthetic disk full')):
            with self.assertRaises(OSError): self.results(self.complete())
        self.preserved()

    def test_replace_failure_cleans_temporary_and_preserves_feed(self):
        with mock.patch.object(meals.os, 'replace', side_effect=OSError('synthetic replace denied')):
            with self.assertRaises(OSError): self.results(self.complete())
        self.preserved()

    def test_chmod_failure_cleans_temporary_and_preserves_feed(self):
        with mock.patch.object(meals.os, 'chmod', side_effect=OSError('synthetic chmod denied')):
            with self.assertRaises(OSError): self.results(self.complete())
        self.preserved()

    def test_temp_creation_failure_preserves_feed(self):
        with mock.patch.object(meals.tempfile, 'NamedTemporaryFile', side_effect=OSError('synthetic create denied')):
            with self.assertRaises(OSError): self.results(self.complete())
        self.preserved()

    def test_reader_observes_old_complete_feed_until_atomic_replace(self):
        replace = meals.os.replace
        with mock.patch.object(meals.os, 'fsync', wraps=meals.os.fsync) as fsync:
            def observation(source, destination):
                self.assertEqual(self.path.read_bytes(), self.before)
                self.assertEqual(self.path.stat().st_mtime_ns, self.mtime)
                self.assertEqual(pathlib.Path(source).parent, self.path.parent)
                self.assertEqual(json.loads(pathlib.Path(source).read_text())['days'], {'new': {'lunch': ['합성 새 점심']}})
                fsync.assert_called_once()
                return replace(source, destination)
            with mock.patch.object(meals.os, 'replace', side_effect=observation):
                meals.write_snapshot(self.path, {'updated': 'new', 'days': {'new': {'lunch': ['합성 새 점심']}}})
        self.assertEqual(json.loads(self.path.read_text())['updated'], 'new')
        self.assertEqual(list(self.path.parent.glob('.*.tmp')), [])

    def test_successful_first_run_creates_parent_and_public_mode(self):
        target = self.path.parent / 'nested' / 'meals.json'
        with mock.patch.object(meals, 'OUT', target): self.assertIs(self.results(self.complete()), True)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
        self.assertEqual(len(json.loads(target.read_text())['days']), COUNT)

    def cli(self, get):
        target = self.path.parent.parent / 'crawler' / 'meals.py'
        target.parent.mkdir(exist_ok=True); target.write_text(pathlib.Path(meals.__file__).read_text())
        with mock.patch.object(meals.requests, 'get', side_effect=get):
            with self.assertRaises(SystemExit) as result: runpy.run_path(str(target), run_name='__main__')
        return result.exception.code

    def test_cli_incomplete_reports_failure_without_changing_synthetic_feed(self):
        self.assertEqual(self.cli(OSError('synthetic offline')), 1)
        self.preserved()

    def test_cli_complete_reports_success(self):
        def get(*args, **kwargs): return types.SimpleNamespace(text=HTML, apparent_encoding='utf-8', encoding=None, raise_for_status=lambda: None)
        self.assertEqual(self.cli(get), 0)
        self.assertTrue(json.loads(self.path.read_text())['days'])


if __name__ == '__main__': unittest.main()
