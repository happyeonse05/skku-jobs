"""Calendar estimates and actual board parsing, using synthetic HTML only."""
import contextlib
import datetime
import io
import json
import pathlib
import tempfile
import types
import unittest
from unittest import mock

from crawler import jobs


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch('requests.sessions.Session.request',
                                     side_effect=AssertionError('external request forbidden')))

    def due(self, today, title):
        with mock.patch.object(jobs, 'TODAY', datetime.date.fromisoformat(today)):
            return jobs.find_due(title)

    def test_leap_day_rollover_to_non_leap_year_is_unestimated(self):
        for title in ['합성 모집 ~2/29', '합성 모집 2월 29일까지', '합성 모집 (~02.29.)']:
            with self.subTest(title=title):
                self.assertEqual(self.due('2024-11-26', title), (None, None))

    def test_leap_day_in_current_year_is_valid(self):
        due, text = self.due('2024-01-01', '합성 모집 ~2/29')
        self.assertEqual(due, '2024-02-29')
        self.assertEqual(text, '~2/29')

    def test_recent_past_leap_day_keeps_existing_policy(self):
        self.assertEqual(self.due('2024-03-01', '합성 모집 ~2/29')[0], '2024-02-29')

    def test_impossible_current_year_dates_remain_unestimated(self):
        for text in ['~2/29', '~2/30', '~4/31', '~13/1', '~0/10']:
            with self.subTest(text=text):
                self.assertEqual(self.due('2025-11-26', text), (None, None))

    def test_new_year_rollover_and_ninety_day_boundary_are_unchanged(self):
        self.assertEqual(self.due('2026-12-15', '합성 모집 ~1/10')[0], '2027-01-10')
        self.assertEqual(self.due('2024-05-29', '합성 모집 ~2/29')[0], '2024-02-29')
        self.assertEqual(self.due('2024-05-30', '합성 모집 ~2/29'), (None, None))
        self.assertEqual(self.due('2026-11-26', '합성 모집 ~12/31')[0], '2026-12-31')

    def test_missing_deadline_and_original_formats_are_unchanged(self):
        self.assertEqual(self.due('2026-11-26', '합성 상시 모집'), (None, None))
        for text in ['~12/31', '∼12.31', '12월 31일까지']:
            with self.subTest(text=text):
                due, matched = self.due('2026-11-26', '합성 모집 '+text)
                self.assertEqual(due, '2026-12-31');self.assertTrue(matched)

    def test_leap_notice_does_not_drop_board_or_later_articles(self):
        html = '<ul><li><a href="?articleNo=101">합성 모집 ~2/29</a><span>2024.11.26</span></li><li><a href="?articleNo=102">합성 모집 ~12/31</a><span>2024.11.25</span></li></ul>'
        response = types.SimpleNamespace(text=html, raise_for_status=lambda: None)
        with mock.patch.object(jobs, 'TODAY', datetime.date(2024,11,26)), mock.patch.object(jobs.requests, 'get', return_value=response):
            items = jobs.crawl_board('합성 게시판', 'https://fixture.invalid/board')
        self.assertEqual(len(items),2)
        self.assertEqual(items[0]['title'],'합성 모집 ~2/29')
        self.assertNotIn('due',items[0]);self.assertNotIn('dueText',items[0])
        self.assertEqual(items[1]['due'],'2024-12-31')
        self.assertEqual([x['posted'] for x in items],['2024-11-26','2024-11-25'])
        self.assertTrue(all(x['writer']=='합성 게시판' and len(x['id'])==12 for x in items))

    def test_full_crawl_publishes_both_boards_without_mutating_meal_feed(self):
        htmls = ['<li><a href="?articleNo=101">합성 채용 ~2/29</a><span>2024.11.26</span></li>',
                 '<li><a href="?articleNo=102">합성 장학 ~12/31</a><span>2024.11.25</span></li>']
        responses = [types.SimpleNamespace(text=s,raise_for_status=lambda:None) for s in htmls]
        with tempfile.TemporaryDirectory() as directory:
            out=pathlib.Path(directory)/'jobs.json';meal=pathlib.Path(directory)/'meals.json';meal.write_bytes(b'keep')
            with mock.patch.object(jobs,'OUT',out), mock.patch.object(jobs,'TODAY',datetime.date(2024,11,26)), mock.patch.object(jobs.requests,'get',side_effect=responses), contextlib.redirect_stdout(io.StringIO()):
                jobs.main()
            items=json.loads(out.read_text())['items']
            self.assertEqual(len(items),2)
            self.assertEqual({x['writer'] for x in items},{b[0] for b in jobs.BOARDS})
            self.assertNotIn('due',items[0]);self.assertEqual(items[1]['due'],'2024-12-31')
            self.assertEqual(meal.read_bytes(),b'keep')


if __name__ == '__main__': unittest.main()
