import os, sys, unittest
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import duty_rules as d

NOW = datetime(2026, 10, 25, 12, 0)

def ev(date, time, typ="Flight", status="Scheduled"):
    return {"date": date, "time": time, "type": typ, "lesson": "X", "status": status}

def periods(*evs):
    return d.build_duty_periods(list(evs), NOW)

class DutyTests(unittest.TestCase):
    def test_exact_12h_gap_is_legal_rest(self):
        p = periods(ev("20 OCT", "06:00 - 09:00"), ev("20 OCT", "21:00 - 23:00"))
        self.assertEqual(len(p), 2)
        self.assertTrue(all(x["hours"] <= 12 for x in p))

    def test_gap_under_12h_is_one_duty_period(self):
        p = periods(ev("20 OCT", "06:00 - 09:00"), ev("20 OCT", "20:59 - 22:00"))
        self.assertEqual(len(p), 1)
        self.assertAlmostEqual(p[0]["hours"], 16.0)

    def test_span_over_12h_warns(self):
        a, b = ev("20 OCT", "06:00 - 09:00"), ev("20 OCT", "17:00 - 19:00")
        w = d.evaluate_event(b, [a, b], NOW)
        self.assertTrue(any("Duty Day Span" in x for x in w))

    def test_overnight_crosses_midnight_into_next_morning(self):
        a = ev("20 OCT", "20:30 - 01:30 (+1D)")
        b = ev("21 OCT", "06:00 - 09:00")   # only 4.5h after a ends -> same duty period
        p = periods(a, b)
        self.assertEqual(len(p), 1)
        self.assertAlmostEqual(p[0]["hours"], 12.5)

    def test_overnight_then_12h_gap_resets(self):
        p = periods(ev("20 OCT", "20:30 - 01:30 (+1D)"), ev("21 OCT", "13:30 - 16:00"))
        self.assertEqual(len(p), 2)

    def test_explicit_rest_period_resets(self):
        p = periods(ev("20 OCT", "06:00 - 10:00"), ev("20 OCT", "10:00 - 14:00", typ="Rest Period"),
                    ev("20 OCT", "15:00 - 20:00"))
        self.assertEqual(len(p), 2)

    def test_cancelled_ignored(self):
        p = periods(ev("20 OCT", "06:00 - 09:00"), ev("20 OCT", "20:00 - 22:00", status="Cancelled"))
        self.assertEqual(len(p), 1)

    def test_eight_days_ok_nine_warns(self):
        days = [ev(f"{n} OCT", "10:00 - 12:00") for n in range(1, 10)]
        self.assertEqual(d.evaluate_event(days[7], days[:8], NOW), [])
        w = d.evaluate_event(days[8], days, NOW)
        self.assertTrue(any("Consecutive" in x for x in w))

    def test_day_off_breaks_streak(self):
        days = [ev(f"{n} OCT", "10:00 - 12:00") for n in (1, 2, 3, 4, 5, 6, 7, 8, 10)]
        self.assertEqual(d.evaluate_event(days[-1], days, NOW), [])

    def test_streak_ending(self):
        dates = d.duty_dates(periods(*[ev(f"{n} OCT", "10:00 - 12:00") for n in (23, 24, 25)]))
        self.assertEqual(d.streak_ending(dates, NOW.date()), 3)

if __name__ == "__main__":
    unittest.main()
