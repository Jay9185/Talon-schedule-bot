"""Shared duty / rest rules for the Talon schedule bot.

Rules:
  1. A duty period (a "working day") starts at the first event's start time
     ("mission start") and may not run longer than 12 hours.
  2. A gap of 12 hours or more between the end of one event and the start of
     the next is a legal rest: the next event begins a NEW duty period.
     (06:00-09:00 followed by a flight at 21:00 is legal - exactly 12 hr gap.)
  3. An explicit "Rest Period" block from the scheduler also starts a new duty period.
  4. At most 8 consecutive working days; a day off is required after the 8th.
"""
from datetime import datetime, timedelta

MAX_DUTY_HOURS = 12.0
MIN_REST_HOURS = 12.0
MAX_CONSECUTIVE_DAYS = 8


def is_cancelled(f):
    status = f.get('status', '').lower()
    return 'cancel' in status or 'cnx' in status


def is_rest_period(f):
    return "Rest Period" in f.get('type', '') or "Rest Period" in f.get('lesson', '')


def _parse_date(d_str, now):
    clean = "".join(c for c in d_str if c.isalnum() or c.isspace()).strip()
    dt = datetime.strptime(f"{clean} {now.year}", "%d %b %Y")
    if dt.month == 12 and now.month < 3:
        dt = dt.replace(year=now.year - 1)
    elif dt.month < 3 and now.month == 12:
        dt = dt.replace(year=now.year + 1)
    return dt


def event_window(f, now):
    """Return (start, end) naive datetimes for an event, or None if unparseable.
    Handles overnight blocks, with or without the '(+1D)' marker."""
    try:
        base = _parse_date(f['date'], now)
        start_s, end_s = f['time'].split("-")
        sh, sm = start_s.strip().split(":")
        eh, em = end_s.split("(")[0].strip().split(":")
        start = base.replace(hour=int(sh), minute=int(sm))
        end = base.replace(hour=int(eh), minute=int(em))
        if "(+1D)" in f['time'] or end < start:
            end += timedelta(days=1)
        return start, end
    except Exception:
        return None


def build_duty_periods(schedule, now):
    """Group non-cancelled events into duty periods.

    Returns a list of dicts: {start, end, hours, events}, chronological.
    `now` is only used to resolve the year of 'DD MON' strings.
    """
    items = []
    for f in schedule:
        if is_cancelled(f):
            continue
        w = event_window(f, now)
        if w:
            items.append((w[0], w[1], f))
    items.sort(key=lambda x: (x[0], x[1]))

    periods = []
    cur = None
    force_break = False
    for start, end, f in items:
        if is_rest_period(f):
            force_break = True
            continue
        gap_ok = cur is not None and (start - cur['end']) >= timedelta(hours=MIN_REST_HOURS)
        if cur is None or force_break or gap_ok:
            cur = {'start': start, 'end': end, 'events': [f]}
            periods.append(cur)
            force_break = False
        else:
            cur['end'] = max(cur['end'], end)
            cur['events'].append(f)

    for p in periods:
        p['hours'] = (p['end'] - p['start']).total_seconds() / 3600
    return periods


def duty_dates(periods):
    """Calendar dates on which a duty period starts."""
    return {p['start'].date() for p in periods}


def consecutive_run(dates, day):
    """(first, last, length) of the consecutive-day run containing `day`,
    or None if `day` is not a working day."""
    if day not in dates:
        return None
    first = last = day
    while first - timedelta(days=1) in dates:
        first -= timedelta(days=1)
    while last + timedelta(days=1) in dates:
        last += timedelta(days=1)
    return first, last, (last - first).days + 1


def streak_ending(dates, day):
    """Consecutive working days counting backwards from `day` (0 if not a working day)."""
    n = 0
    while day in dates:
        n += 1
        day -= timedelta(days=1)
    return n


def evaluate_event(target, schedule, now):
    """Warnings for one event, using the shared rules."""
    if is_cancelled(target) or is_rest_period(target):
        return []
    warnings = []
    periods = build_duty_periods(schedule, now)

    period = next((p for p in periods if any(e is target for e in p['events'])), None)
    if period is None:  # target is a copy rather than the same object
        key = (target.get('date'), target.get('time'))
        period = next((p for p in periods
                       if any((e.get('date'), e.get('time')) == key for e in p['events'])), None)
    if period is None:
        return warnings

    if period['hours'] > MAX_DUTY_HOURS:
        warnings.append(
            f"Duty Day Span: {period['hours']:.1f} Hours "
            f"({period['start'].strftime('%H:%M')}-{period['end'].strftime('%H:%M')}, "
            f"limit {MAX_DUTY_HOURS:.0f})"
        )

    run = consecutive_run(duty_dates(periods), period['start'].date())
    if run and run[2] > MAX_CONSECUTIVE_DAYS:
        warnings.append(
            f"Consecutive Days: {run[2]} Days (Requires 1 day off after {MAX_CONSECUTIVE_DAYS})"
        )
    return warnings
