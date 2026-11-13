"""The calendar widget: the next meeting from the iCal address of a Google, Outlook or iCloud calendar.

The address is the calendar's own secret iCal link (Google: Settings -> the calendar -> "Secret address in iCal
format"; Outlook: Settings -> Calendar -> Shared calendars -> Publish a calendar -> ICS). Tessera reads it in the
background every few minutes, only when an address is set, and never sends anything to it.

Times with a time zone (TZID) are read as local time: Windows Python has no time zone database, and a calendar
someone looks at on their own desk is nearly always in the PC's zone. UTC times (ending in Z) are converted.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
import threading
import time
import urllib.parse
import urllib.request

REFRESH_SECONDS = 300
RETRY_SECONDS = 60
MAX_BYTES = 2 * 1024 * 1024
MAX_URL = 500
LOOK_AHEAD = timedelta(days=2)
DAYS = ('MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU')
DURATION = re.compile(r'([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$')


def fetch_url(url: str) -> str:
    """webcal:// is https:// with another name; anything but a web address is refused."""
    if url.lower().startswith('webcal://'):
        url = 'https://' + url[9:]
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('The calendar address must start with https://, http:// or webcal://')
    return url


def check_settings(settings) -> None:
    """Validate the `calendar` block of the configuration."""
    if not isinstance(settings, dict) or set(settings) - {'url'} or not isinstance(settings.get('url'), str):
        raise ValueError('calendar needs a url')
    if not 0 < len(settings['url']) <= MAX_URL:
        raise ValueError(f'The calendar address must be 1-{MAX_URL} characters')
    fetch_url(settings['url'])


# --- reading an iCal file ----------------------------------------------------------------------------------------

def _lines(text: str):
    """Unfolded property lines: a line that starts with a space or a tab continues the one before."""
    lines: list[str] = []
    for raw in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if raw[:1] in (' ', '\t') and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _property(line: str):
    """'DTSTART;TZID=Europe/Oslo:20261113T090000' -> ('DTSTART', {'TZID': 'Europe/Oslo'}, '20261113T090000')."""
    # The value starts at the first ':' outside double quotes: Outlook writes TZID="(UTC+01:00) Amsterdam ...".
    quoted, split = False, len(line)
    for index, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == ':' and not quoted:
            split = index
            break
    head, value = line[:split], line[split + 1:]
    name, *params = head.split(';')
    return name.upper(), dict(param.partition('=')[::2] for param in params), value


def _when(value: str, params: dict):
    """A date (all day) or a local datetime without time zone."""
    value = value.strip()
    if params.get('VALUE') == 'DATE' or len(value) == 8:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    moment = datetime(int(value[:4]), int(value[4:6]), int(value[6:8]), int(value[9:11]), int(value[11:13]),
                      int(value[13:15] or 0))
    if value.endswith('Z'):
        moment = moment.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    return moment


def _duration(value: str) -> timedelta:
    match = DURATION.match(value.strip())
    if not match:
        raise ValueError(f'Unknown duration {value!r}')
    sign, weeks, days, hours, minutes, seconds = match.groups()
    length = timedelta(weeks=int(weeks or 0), days=int(days or 0), hours=int(hours or 0),
                       minutes=int(minutes or 0), seconds=int(seconds or 0))
    return -length if sign == '-' else length


def _as_datetime(value) -> datetime:
    return value if isinstance(value, datetime) else datetime(value.year, value.month, value.day)


def _events(text: str) -> list[dict]:
    events, current = [], None
    for line in _lines(text):
        name, params, value = _property(line)
        if name == 'BEGIN' and value.upper() == 'VEVENT':
            current = {'exdates': set()}
        elif name == 'END' and value.upper() == 'VEVENT' and current is not None:
            if 'start' in current:
                events.append(current)
            current = None
        elif current is None:
            continue
        elif name in ('DTSTART', 'DTEND', 'RECURRENCE-ID', 'DURATION', 'EXDATE'):
            try:
                if name == 'DURATION':
                    current['duration'] = _duration(value)
                elif name == 'EXDATE':
                    current['exdates'].update(_when(item, params) for item in value.split(',') if item.strip())
                else:
                    key = {'DTSTART': 'start', 'DTEND': 'end', 'RECURRENCE-ID': 'recurrence'}[name]
                    current[key] = _when(value, params)
            except (ValueError, IndexError):  # one unreadable event is dropped, not the whole calendar
                current = None
        elif name == 'SUMMARY':
            current['summary'] = value.replace('\\,', ',').replace('\\;', ';').replace('\\n', ' ').replace('\\\\', '\\').strip()
        elif name == 'RRULE':
            current['rrule'] = dict(part.partition('=')[::2] for part in value.split(';') if part)
        elif name in ('UID', 'STATUS'):
            current[name.lower()] = value.strip()
    return events


def _add_months(day: date, months: int) -> tuple[int, int]:
    index = day.year * 12 + day.month - 1 + months
    return index // 12, index % 12 + 1


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date | None:
    """The nth (1-5, or -1 for the last) weekday of a month."""
    first = date(year, month, 1)
    following = date(year + month // 12, month % 12 + 1, 1)
    days = [first + timedelta(days=offset) for offset in range((following - first).days)]
    matches = [day for day in days if day.weekday() == weekday]
    try:
        return matches[nth - 1] if nth > 0 else matches[nth]
    except IndexError:
        return None


def _starts(event: dict, until: datetime):
    """Every start of the event up to `until`, its repeat rule followed (daily, weekly, monthly, yearly)."""
    start = event['start']
    rule = event.get('rrule')
    if not rule:
        yield start
        return
    frequency, interval = rule.get('FREQ', ''), max(1, int(rule.get('INTERVAL', 1) or 1))
    count = int(rule['COUNT']) if rule.get('COUNT', '').isdigit() else None
    end = _when(rule['UNTIL'], {}) if rule.get('UNTIL') else None
    if end is not None and not isinstance(end, datetime):
        end = _as_datetime(end) + timedelta(days=1) - timedelta(microseconds=1)  # a date UNTIL includes that whole day
    by_day = [item for item in rule.get('BYDAY', '').split(',') if item]
    clock = start - datetime.combine(start.date(), datetime.min.time()) if isinstance(start, datetime) else timedelta()
    first = start.date() if isinstance(start, datetime) else start
    days = sorted(DAYS.index(day[-2:]) for day in by_day) or [first.weekday()]
    made = 0

    def at(day: date):
        return datetime.combine(day, datetime.min.time()) + clock if isinstance(start, datetime) else day

    skip = 0
    if frequency in ('DAILY', 'WEEKLY'):  # jump over the years before the window instead of walking them
        period = interval * (1 if frequency == 'DAILY' else 7)
        skip = max(0, ((until - LOOK_AHEAD * 2).date() - first).days // period - 1)
        if skip:  # what COUNT has already used up in the skipped weeks or days
            made = skip if frequency == 'DAILY' else skip * len(days) - sum(day < first.weekday() for day in days)

    def candidates():
        step = skip
        for _ in range(5000):
            if frequency == 'DAILY':
                yield first + timedelta(days=step * interval)
            elif frequency == 'WEEKLY':
                monday = first - timedelta(days=first.weekday()) + timedelta(weeks=step * interval)
                for weekday in days:
                    yield monday + timedelta(days=weekday)
            elif frequency == 'MONTHLY':
                year, month = _add_months(first, step * interval)
                if by_day:
                    # BYDAY=2TU is one day; a bare BYDAY=FR is every Friday, which BYSETPOS (-1: the last) narrows.
                    # Sorted, because the early stop below assumes the dates come in order.
                    month_days = set()
                    for item in by_day:
                        weekday = DAYS.index(item[-2:])
                        if item[:-2]:
                            month_days.add(_nth_weekday(year, month, weekday, int(item[:-2])))
                        else:
                            month_days.update(_nth_weekday(year, month, weekday, nth) for nth in range(1, 6))
                    month_days = sorted(day for day in month_days if day)
                    positions = [int(value) for value in str(rule.get('BYSETPOS', '')).split(',') if value]
                    if positions:
                        month_days = sorted({month_days[pos - 1 if pos > 0 else pos] for pos in positions
                                             if pos and -len(month_days) <= (pos - 1 if pos > 0 else pos) < len(month_days)})
                    yield from month_days
                else:
                    last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
                    wanted = (int(value) for value in str(rule.get('BYMONTHDAY', first.day)).split(',') if value)
                    for day_of_month in sorted(last + item + 1 if item < 0 else item for item in wanted):  # -1: last day
                        if 1 <= day_of_month <= last:
                            yield date(year, month, day_of_month)
            elif frequency == 'YEARLY':
                year = first.year + step * interval
                try:
                    yield first.replace(year=year)
                except ValueError:  # 29 February
                    pass
            else:
                yield first
                return
            step += 1

    for day in candidates():
        if day < first:
            continue
        moment = at(day)
        if _as_datetime(moment) > until or (end and _as_datetime(moment) > end):
            return
        made += 1
        if count is not None and made > count:
            return
        yield moment


def upcoming(text: str, now: datetime) -> list[dict]:
    """The events from twelve hours ago to two days ahead, sorted, as {'start', 'end', 'summary', 'all_day'}."""
    until = now + LOOK_AHEAD
    events = _events(text)
    moved = {(event.get('uid'), event['recurrence']) for event in events if 'recurrence' in event}
    found = []
    for event in events:
        if event.get('status', '').upper() == 'CANCELLED':
            continue
        start = event['start']
        length = (_as_datetime(event['end']) - _as_datetime(start)) if 'end' in event else event.get('duration')
        if length is None:
            length = timedelta(days=1) if not isinstance(start, datetime) else timedelta()
        try:
            starts = list(_starts(event, until))
        except (ValueError, KeyError, IndexError, OverflowError):  # a rule this reader does not understand
            starts = [start]
        for moment in starts:
            cancelled = moment in event['exdates'] or (isinstance(moment, datetime) and moment.date() in event['exdates'])
            if 'rrule' in event and (cancelled or (event.get('uid'), moment) in moved):
                continue
            begin = _as_datetime(moment)
            finish = begin + length
            if finish > now - timedelta(hours=12) and begin <= until:
                found.append({'start': begin, 'end': finish, 'summary': event.get('summary') or 'Busy',
                              'all_day': not isinstance(moment, datetime)})
    return sorted(found, key=lambda item: (item['start'], item['summary']))


# --- the widget --------------------------------------------------------------------------------------------------

def _wait(minutes: int) -> str:
    if minutes < 1:
        return 'now'
    if minutes < 60:
        return f'in {minutes} min'
    hours, rest = divmod(minutes, 60)
    return f'in {hours} h {rest} min' if rest else f'in {hours} h'


def content(events: list[dict] | None, now: datetime, error: str = '') -> dict:
    """Title, second line and progress for a wide key: the meeting that runs now, else the next one."""
    if events is None:
        return {'label': 'Calendar', 'sub': error or 'Add your calendar in Program settings'}
    timed = [event for event in events if not event['all_day']]
    running = next((event for event in timed if event['start'] <= now < event['end']), None)
    if running:
        total = (running['end'] - running['start']).total_seconds() or 1
        return {'label': running['summary'], 'sub': f"Now · until {running['end']:%H:%M}",
                'progress': max(0, min(100, round((now - running['start']).total_seconds() / total * 100)))}
    later = next((event for event in timed if event['start'] > now), None)
    if later and later['start'].date() == now.date():
        return {'label': later['summary'], 'sub': f"{later['start']:%H:%M} · {_wait(int((later['start'] - now).total_seconds() // 60))}"}
    today = next((event for event in events if event['all_day'] and event['start'].date() <= now.date() < event['end'].date()), None)
    if today:
        return {'label': today['summary'], 'sub': 'All day'}
    if later and later['start'].date() == now.date() + timedelta(days=1):
        return {'label': later['summary'], 'sub': f"Tomorrow {later['start']:%H:%M}"}
    return {'label': 'No meetings', 'sub': 'Nothing more today'}


class Feed:
    """Keeps the calendar fresh in the background, like the weather on the ambient screen."""

    def __init__(self, opener=urllib.request.urlopen, clock=time.monotonic):
        self._opener, self._clock = opener, clock
        self._lock = threading.Lock()
        self._url = None
        self._text = None
        self._error = ''
        self._next = 0.0
        self._busy = False
        self._parsed = (None, None, None)  # (text, minute, events): read once a minute, not on every refresh

    def events(self, settings: dict | None, now: datetime) -> tuple[list[dict] | None, str]:
        """The upcoming events and an error text; (None, '') without an address. Starts a refresh when due."""
        url = (settings or {}).get('url')
        if not url:
            return None, ''
        with self._lock:
            if url != self._url:
                self._url, self._text, self._error, self._next = url, None, '', 0.0
            if self._clock() >= self._next and not self._busy:
                self._busy = True
                threading.Thread(target=self._refresh, args=(url,), name='calendar', daemon=True).start()
            text, error = self._text, self._error
        if text is None:
            return None, error or 'Reading the calendar …'
        minute = now.replace(second=0, microsecond=0)
        if self._parsed[0] is text and self._parsed[1] == minute:
            return self._parsed[2], ''
        try:
            found = upcoming(text, minute)
            self._parsed = (text, minute, found)
            return found, ''
        except (ValueError, KeyError, IndexError) as exc:
            return None, f'The calendar could not be read: {exc}'[:60]

    def _refresh(self, url: str) -> None:
        text, error = None, ''
        try:
            request = urllib.request.Request(fetch_url(url), headers={'User-Agent': 'Tessera'})
            with self._opener(request, timeout=10) as response:
                data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('the calendar is larger than 2 MB')
            text = data.decode('utf-8', 'replace')
            if 'BEGIN:VCALENDAR' not in text[:2000].upper():
                text, error = None, 'That address is not an iCal calendar'
        except Exception as exc:  # any failure must clear _busy below, or the calendar would never refresh again
            error = f'Could not read the calendar: {exc}'[:60]
        with self._lock:
            if url == self._url:
                if text is not None:
                    self._text, self._error = text, ''
                elif self._text is None:
                    self._error = error
                self._next = self._clock() + (REFRESH_SECONDS if text is not None else RETRY_SECONDS)
            else:  # the address changed while this ran: fetch the new one on the next call, not in 5 minutes
                self._next = 0.0
            self._busy = False
