"""Money is whole dinar and rounding is predictable."""
import unittest

from datetime import datetime

from ledger.dates import tonight
from ledger.money import mround, pct, split_shares, to_int


class ToInt(unittest.TestCase):
    def test_accepts_what_a_form_sends(self):
        self.assertEqual(to_int(""), 0)
        self.assertEqual(to_int(None), 0)
        self.assertEqual(to_int("5000"), 5000)
        self.assertEqual(to_int("5,000"), 5000)
        self.assertEqual(to_int(" 5000 "), 5000)
        self.assertEqual(to_int(5000.0), 5000)

    def test_rounds_a_stored_half_dinar(self):
        # Half away from zero, the same rule as mround, so a figure carried in
        # from the Excel workbook rounds the same way wherever it is touched.
        self.assertEqual(to_int(1234567.5), 1234568)
        self.assertEqual(to_int(-1234567.5), -1234568)

    def test_it_does_not_use_bankers_rounding(self):
        self.assertEqual(to_int(0.5), 1)        # Python's round() gives 0
        self.assertEqual(to_int(1.5), 2)
        self.assertEqual(to_int(2.5), 3)        # Python's round() gives 2

    def test_refuses_nonsense_rather_than_quietly_returning_zero(self):
        for bad in ("abc", "1,2,x", True, float("nan"), float("inf"), [1]):
            with self.assertRaises(ValueError):
                to_int(bad)


class Rounding(unittest.TestCase):
    def test_rounds_to_the_note(self):
        self.assertEqual(mround(0), 0)
        self.assertEqual(mround(124), 0)
        self.assertEqual(mround(125), 250)
        self.assertEqual(mround(374), 250)
        self.assertEqual(mround(375), 500)
        self.assertEqual(mround(5000), 5000)

    def test_halves_go_away_from_zero_both_ways(self):
        self.assertEqual(mround(125), 250)
        self.assertEqual(mround(-125), -250)

    def test_a_note_of_one_leaves_the_figure_alone(self):
        self.assertEqual(mround(1237, note=1), 1237)


class Shares(unittest.TestCase):
    def test_an_even_split_is_even(self):
        out = split_shares(1000000, [("A", 0.5), ("B", 0.5)])
        self.assertEqual(out, {"A": 500000, "B": 500000})

    def test_the_parts_always_add_back_to_the_whole(self):
        for total in (0, 250, 1000, 1000500, -2000250, 7000001):
            for shares in ([("A", 0.5), ("B", 0.5)],
                           [("A", 1 / 3), ("B", 1 / 3), ("C", 1 / 3)],
                           [("A", 0.7), ("B", 0.2), ("C", 0.1)]):
                out = split_shares(total, shares)
                self.assertEqual(sum(out.values()), total,
                                 f"{total} across {shares} -> {out}")

    def test_the_remainder_does_not_depend_on_row_order(self):
        a = split_shares(1000, [("A", 0.7), ("B", 0.3)])
        b = split_shares(1000, [("B", 0.3), ("A", 0.7)])
        self.assertEqual(a, b)

    def test_an_even_net_splits_in_half(self):
        out = split_shares(1000500, [("Erin Moss", 0.5), ("Frank Hale", 0.5)])
        self.assertEqual(sum(out.values()), 1000500)
        self.assertEqual(set(out.values()), {500250})


class Pct(unittest.TestCase):
    def test_no_division_by_zero(self):
        self.assertIsNone(pct(5, 0))
        self.assertEqual(pct(1260000, 10000000), 12.6)



class FarTooLarge(unittest.TestCase):
    """A 20-digit figure pasted into an amount crashed with "Python int too
    large to convert to SQLite INTEGER"; one a little shorter was saved."""

    def test_a_figure_no_business_holds_is_refused_plainly(self):
        for v in ("12345678901234567890", "6281234567890", 10 ** 13):
            with self.assertRaises(ValueError) as cm:
                to_int(v)
            self.assertIn("far too large", str(cm.exception))

    def test_a_large_real_figure_is_still_taken(self):
        self.assertEqual(to_int("999,999,999,999"), 999999999999)

    def test_through_an_action_it_is_a_refusal_not_a_crash(self):
        from ledger import api
        from tests.helpers import fresh_books
        with self.assertRaises(api.ApiError):
            api.run(fresh_books(), "sales", {"amount": "12345678901234567890", "on": "2026-11-09"})

class TheNight(unittest.TestCase):
    """The lounge closes after midnight: until six in the morning it is still
    the night before, so a till figure typed at one in the morning belongs to
    the night it was taken."""

    def test_after_midnight_is_still_last_night(self):
        self.assertEqual(tonight(datetime(2026, 11, 13, 1, 30)), "2026-11-12")
        self.assertEqual(tonight(datetime(2026, 11, 13, 5, 59)), "2026-11-12")

    def test_from_six_it_is_the_new_day(self):
        self.assertEqual(tonight(datetime(2026, 11, 13, 6, 0)), "2026-11-13")
        self.assertEqual(tonight(datetime(2026, 11, 13, 23, 0)), "2026-11-13")

    def test_the_first_of_the_month_at_one_is_still_the_month_before(self):
        # a count taken after the last night of October is October's count
        self.assertEqual(tonight(datetime(2026, 11, 1, 1, 0)), "2026-10-31")


if __name__ == "__main__":
    unittest.main()
