"""The Next meeting widget: an iCal calendar read in the background, repeats and exceptions followed."""
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import calendar_feed  # noqa: E402
from import_review import redact_secrets  # noqa: E402
import host_support  # noqa: E402

NOW = datetime(2026, 11, 13, 9, 10)  # a Friday


def ics(*events):
    body = ''.join('BEGIN:VEVENT\r\n' + ''.join(line + '\r\n' for line in event) + 'END:VEVENT\r\n' for event in events)
    return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + body + 'END:VCALENDAR\r\n'


def summaries(text, now=NOW):
    return [(event['start'].strftime('%a %H:%M'), event['summary']) for event in calendar_feed.upcoming(text, now)]


class ReadingTests(unittest.TestCase):
    def test_single_all_day_and_folded_events(self):
        text = ics(['UID:a', 'DTSTART:20261113T093000', 'DTEND:20261113T100000', 'SUMMARY:Design re', ' view'],
                   ['UID:b', 'DTSTART;VALUE=DATE:20261113', 'SUMMARY:Holiday'],
                   ['UID:c', 'DTSTART:20261120T090000', 'SUMMARY:Too far ahead'],
                   ['UID:d', 'DTSTART:20261113T110000', 'STATUS:CANCELLED', 'SUMMARY:Called off'])
        self.assertEqual(summaries(text), [('Fri 00:00', 'Holiday'), ('Fri 09:30', 'Design review')])

    def test_utc_times_are_shown_in_local_time(self):
        utc = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
        local = utc.astimezone().replace(tzinfo=None)
        event = calendar_feed.upcoming(ics(['DTSTART:20261113T090000Z', 'DURATION:PT30M', 'SUMMARY:Sync']), NOW)[0]
        self.assertEqual((event['start'], event['end'] - event['start']), (local, timedelta(minutes=30)))

    def test_weekly_repeats_skip_cancelled_and_moved_meetings(self):
        text = ics(['UID:standup', 'DTSTART;TZID=Europe/Oslo:20250106T091500', 'DTEND;TZID=Europe/Oslo:20250106T093000',
                    'RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR', 'EXDATE;TZID=Europe/Oslo:20261116T091500', 'SUMMARY:Standup'],
                   ['UID:standup', 'RECURRENCE-ID;TZID=Europe/Oslo:20261113T091500', 'DTSTART:20261113T101500',
                    'DTEND:20261113T103000', 'SUMMARY:Standup (moved)'])
        found = summaries(text)
        self.assertIn(('Fri 10:15', 'Standup (moved)'), found)
        self.assertNotIn(('Fri 09:15', 'Standup'), found, 'the moved meeting is not also shown at its old time')
        self.assertNotIn(('Mon 09:15', 'Standup'), found, 'a cancelled date is left out')
        self.assertIn(('Sat 09:15', 'Standup'), summaries(text.replace('MO,WE,FR', 'SA')))

    def test_daily_count_until_monthly_and_yearly_rules(self):
        self.assertEqual(summaries(ics(['DTSTART:20261110T080000', 'RRULE:FREQ=DAILY;COUNT=4', 'SUMMARY:Course'])),
                         [('Fri 08:00', 'Course')])
        self.assertEqual(summaries(ics(['DTSTART:20261101T080000', 'RRULE:FREQ=DAILY;UNTIL=20261113', 'SUMMARY:Ends'])),
                         [('Fri 08:00', 'Ends')])
        self.assertEqual(summaries(ics(['DTSTART:20260109T150000', 'RRULE:FREQ=MONTHLY;BYDAY=2FR', 'SUMMARY:Review'])),
                         [('Fri 15:00', 'Review')])
        self.assertEqual(summaries(ics(['DTSTART;VALUE=DATE:19801113', 'RRULE:FREQ=YEARLY', 'SUMMARY:Birthday'])),
                         [('Fri 00:00', 'Birthday')])

    def test_until_count_month_days_and_odd_rules(self):
        until = ics(['DTSTART:20261111T091000', 'RRULE:FREQ=DAILY;UNTIL=20261113T091000', 'SUMMARY:Last'])
        self.assertEqual(summaries(until), [('Fri 09:10', 'Last')], 'UNTIL at the start time includes it')
        old = ics(['DTSTART:20000101T080000', 'RRULE:FREQ=DAILY;COUNT=9814', 'SUMMARY:Long'])
        self.assertEqual(summaries(old), [('Fri 08:00', 'Long')], 'the 9814th day is today, the last one')
        self.assertEqual(summaries(ics(['DTSTART:20000101T080000', 'RRULE:FREQ=DAILY;COUNT=5', 'SUMMARY:Over'])), [])
        last = ics(['DTSTART:20261031T120000', 'RRULE:FREQ=MONTHLY;BYMONTHDAY=13,-1', 'SUMMARY:Pay'])
        self.assertEqual(summaries(last), [('Fri 12:00', 'Pay')])
        weird = ics(['DTSTART:20261113T130000', 'RRULE:FREQ=MONTHLY;BYDAY=XX', 'SUMMARY:Odd'], ['DTSTART:20261113T140000', 'SUMMARY:Fine'])
        self.assertEqual(summaries(weird), [('Fri 13:00', 'Odd'), ('Fri 14:00', 'Fine')], 'an odd rule hides nothing else')
        dated = ics(['DTSTART:20261111T091000', 'RRULE:FREQ=DAILY', 'EXDATE;VALUE=DATE:20261113', 'SUMMARY:Daily'])
        self.assertNotIn(('Fri 09:10', 'Daily'), summaries(dated), 'a date in EXDATE cancels that day')


class WidgetTests(unittest.TestCase):
    def events(self, *lines):
        return calendar_feed.upcoming(ics(*lines), NOW)

    def test_what_the_key_shows(self):
        content = calendar_feed.content
        self.assertEqual(content(None, NOW)['sub'], 'Add your calendar in Program settings')
        running = content(self.events(['DTSTART:20261113T090000', 'DTEND:20261113T093000', 'SUMMARY:Standup']), NOW)
        self.assertEqual((running['label'], running['sub'], running['progress']), ('Standup', 'Now · until 09:30', 33))
        later = content(self.events(['DTSTART:20261113T103500', 'DTEND:20261113T110000', 'SUMMARY:Planning']), NOW)
        self.assertEqual((later['label'], later['sub']), ('Planning', '10:35 · in 1 h 25 min'))
        self.assertEqual(content(self.events(['DTSTART;VALUE=DATE:20261113', 'SUMMARY:Holiday']), NOW)['sub'], 'All day')
        trip = self.events(['DTSTART;VALUE=DATE:20261111', 'DTEND;VALUE=DATE:20261115', 'SUMMARY:Trip'])
        self.assertEqual(content(trip, NOW)['label'], 'Trip', 'an all-day event over several days shows on each one')
        tomorrow = content(self.events(['DTSTART:20261114T100000', 'SUMMARY:Brunch']), NOW)
        self.assertEqual((tomorrow['label'], tomorrow['sub']), ('Brunch', 'Tomorrow 10:00'))
        self.assertEqual(content([], NOW)['label'], 'No meetings')


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FeedTests(unittest.TestCase):
    def settle(self, feed):
        for _ in range(250):
            if not feed._busy:
                return
            time.sleep(0.02)
        self.fail('the calendar refresh did not finish')

    def test_the_feed_reads_in_the_background_and_keeps_the_last_good_calendar(self):
        clock, answers, asked = [0.0], [ics(['DTSTART:20261113T110000', 'SUMMARY:Lunch']).encode()], []

        def opener(request, timeout):
            asked.append(request.full_url)
            if not answers:
                raise OSError('offline')
            return Reply(answers.pop())

        feed = calendar_feed.Feed(opener, clock=lambda: clock[0])
        settings = {'url': 'webcal://example.com/basic.ics'}
        self.assertEqual(feed.events(None, NOW), (None, ''))
        self.assertEqual(feed.events(settings, NOW)[0], None, 'nothing yet: the first read runs in the background')
        self.settle(feed)
        self.assertEqual(asked, ['https://example.com/basic.ics'])
        self.assertEqual(feed.events(settings, NOW)[0][0]['summary'], 'Lunch')
        clock[0] += calendar_feed.REFRESH_SECONDS + 1
        feed.events(settings, NOW)
        self.settle(feed)
        self.assertEqual(feed.events(settings, NOW)[0][0]['summary'], 'Lunch', 'a failed refresh keeps the last calendar')

    def test_a_page_that_is_no_calendar_says_so(self):
        feed = calendar_feed.Feed(lambda request, timeout: Reply(b'<html>sign in</html>'))
        feed.events({'url': 'https://example.com/'}, NOW)
        self.settle(feed)
        self.assertEqual(feed.events({'url': 'https://example.com/'}, NOW), (None, 'That address is not an iCal calendar'))

    def test_only_web_addresses_are_accepted(self):
        calendar_feed.check_settings({'url': 'webcal://p01-caldav.icloud.com/published/2/abc'})
        for bad in ({'url': 'file:///C:/x.ics'}, {'url': ''}, {'url': 'https://x', 'extra': 1}, 'https://x'):
            with self.assertRaises(ValueError):
                calendar_feed.check_settings(bad)


class PrivacyAndDaemonTests(unittest.TestCase):
    def test_export_leaves_out_the_calendar_address_and_plugin_secrets(self):
        config = {'calendar': {'url': 'https://calendar.google.com/calendar/ical/secret/basic.ics'},
                  'plugins': {'home-assistant': {'enabled': True, 'settings': {'url': 'http://ha.local:8123', 'token': 'abc'}}},
                  'profiles': {}}
        shared, _ = redact_secrets(config)
        self.assertNotIn('calendar', shared)
        self.assertEqual(shared['plugins']['home-assistant']['settings'], {'url': 'http://ha.local:8123'})
        self.assertIn('calendar', config, 'the configuration itself is not changed')

    def test_a_wide_key_shows_the_next_meeting(self):
        daemon = host_support.test_daemon()
        daemon.config = dict(daemon.config, calendar={'url': 'https://example.com/basic.ics'})
        daemon.calendar.events = lambda settings, now: ([{'start': now + timedelta(minutes=20), 'end': now + timedelta(minutes=50),
                                                          'summary': 'Retro', 'all_day': False}], '')
        self.assertEqual(daemon.live_content('calendar')['label'], 'Retro')
        self.assertEqual(daemon.live_content('calendar')['sub'][-9:], 'in 20 min')


if __name__ == '__main__':
    unittest.main()
