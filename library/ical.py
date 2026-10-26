"""A calendar feed (iCalendar, RFC 5545) of new episodes, releases and saved events."""

from datetime import timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone


def _escape(text):
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    """Lines longer than 75 octets continue on the next line, starting with a space."""
    encoded = line.encode()
    if len(encoded) <= 75:
        return line
    parts, current = [], b""
    for char in line:
        b = char.encode()
        if len(current) + len(b) > 74:
            parts.append(current.decode())
            current = b""
        current += b
    parts.append(current.decode())
    return "\r\n ".join(parts)


def _utc(dt):
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def render(days, host):
    now = _utc(timezone.now())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//liveaux//library//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:liveaux",
    ]
    for day, rows in days:
        for row in rows:
            lines += ["BEGIN:VEVENT", f"UID:{row['uid']}@{host}", f"DTSTAMP:{now}"]
            event = row.get("event")
            if event is not None and not event.is_multi_day:
                end = event.ends_at or event.starts_at + timedelta(hours=2)
                lines += [f"DTSTART:{_utc(event.starts_at)}", f"DTEND:{_utc(end)}"]
            elif event is not None:
                start = timezone.localdate(event.starts_at)
                end = timezone.localdate(event.ends_at) + timedelta(days=1)
                lines += [f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{end:%Y%m%d}"]
            else:
                lines += [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"]
            lines += [
                f"SUMMARY:{_escape(row['title'])}",
                f"DESCRIPTION:{_escape(row['label'] + ' · ' + row['detail'])}",
                f"URL:https://{host}{row['url']}",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
