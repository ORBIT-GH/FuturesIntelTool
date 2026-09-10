from __future__ import annotations

import unittest
from datetime import date

from futures_intel.calendar import is_trading_day


class TradingCalendarTest(unittest.TestCase):
    def test_weekends_and_holidays_are_closed(self) -> None:
        config = {"market_holidays_file": "config/market_holidays.txt", "project_root": "."}
        self.assertFalse(is_trading_day(date(2026, 9, 12), config))
        self.assertFalse(is_trading_day(date(2026, 10, 1), config))
        self.assertTrue(is_trading_day(date(2026, 9, 10), config))


if __name__ == "__main__":
    unittest.main()
