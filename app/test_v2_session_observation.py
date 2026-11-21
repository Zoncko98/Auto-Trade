"""Market-session visibility never impersonates live broker market-hours authority."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from trader_v2.session_observation import session_observation
from trader_v2.cutover_preflight import preflight


def instant(year,month,day,hour,minute=0):
    return datetime(year,month,day,hour,minute,tzinfo=timezone.utc)


class SessionObservationTests(TestCase):
    def test_saturday_equity_closed_and_crypto_not_claimed_open(self):
        for broker in ("schwab","webull"):
            item=session_observation(broker,now=instant(2026,11,21,16))
            self.assertEqual(item["state"],"EQUITIES_CLOSED_WEEKEND")
            self.assertFalse(item["broker_session_verified"])
            self.assertFalse(item["executable_market_open"])
        item=session_observation("robinhood_crypto",now=instant(2026,11,21,16))
        self.assertFalse(item["broker_session_verified"])
        self.assertFalse(item["executable_market_open"])

    def test_monday_open_window_requires_broker_holiday_calendar(self):
        # Monday 09:30 ET is 14:30 UTC in November.
        morning=session_observation("schwab",now=instant(2026,11,23,14,30))
        self.assertEqual(morning["state"],"REGULAR_HOURS_WINDOW_HOLIDAYS_UNVERIFIED")
        self.assertFalse(morning["broker_session_verified"])
        self.assertTrue(morning["requires_authenticated_broker_hours"])

    def test_summer_dst_and_regular_close(self):
        # July 6 2026 is a Monday, 9:29 New York daylight time is 13:29 UTC.
        early=session_observation("webull",now=instant(2026,7,6,13,29))
        opened=session_observation("webull",now=instant(2026,7,6,13,30))
        close=session_observation("webull",now=instant(2026,7,6,20))
        self.assertEqual(early["state"],"OUTSIDE_US_REGULAR_TRADING_HOURS")
        self.assertEqual(opened["state"],"REGULAR_HOURS_WINDOW_HOLIDAYS_UNVERIFIED")
        self.assertEqual(close["state"],"OUTSIDE_US_REGULAR_TRADING_HOURS")

    def test_unknown_exchange_holiday_not_guessed_open(self):
        thanksgiving=session_observation("schwab",now=instant(2026,11,26,16))
        self.assertEqual(thanksgiving["state"],"REGULAR_HOURS_WINDOW_HOLIDAYS_UNVERIFIED")
        self.assertFalse(thanksgiving["executable_market_open"])

    def test_invalid_clock_and_broker_refused(self):
        with self.assertRaises(ValueError):
            session_observation("schwab",now=datetime(2026,11,21))
        with self.assertRaises(ValueError):
            session_observation("unknown",now=instant(2026,11,21,16))

    def test_cutover_shows_session_but_no_live_permission(self):
        with TemporaryDirectory() as temp:
            accounts=[{"broker":b,"auth":"CONNECTED","read_verified":True,
                       "permission_armed":True,"worker_state":"ONLINE"}
                      for b in ("schwab","webull","robinhood_crypto","paper")]
            statuses={b:{"state":"FRESH_READ_ONLY"}
                     for b in ("schwab","webull","robinhood_crypto","paper")}
            doc=preflight(Path(temp),accounts,statuses)
            for item in doc["accounts"][:3]:
                self.assertFalse(item["live_order_authority"])
                self.assertFalse(item["ready_for_v2_live"])
                self.assertIn("market_session",item)
                self.assertFalse(item["market_session"]["broker_session_verified"])


if __name__=="__main__":
    main()
