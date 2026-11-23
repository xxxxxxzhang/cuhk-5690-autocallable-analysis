import unittest
from decimal import Decimal as D

from src.data_loader import extend_close_with_current_snapshot, load_market
from src.payoff import load_terms


class CurrentSnapshotExtensionTests(unittest.TestCase):
    def test_replay_extension_reaches_latest_frozen_session(self):
        terms = load_terms()
        archive = load_market(terms)
        merged, metadata = extend_close_with_current_snapshot(archive, terms)

        self.assertEqual(max(archive), "2026-11-06")
        self.assertEqual(max(merged), "2026-11-20")
        self.assertEqual(metadata["extension_sessions"], 10)
        self.assertEqual(merged["2026-11-20"]["AMZN"], D("246.82"))
        self.assertEqual(merged["2026-11-20"]["NVDA"], D("125.53"))
        self.assertEqual(merged["2026-11-20"]["PLTR"], D("143.49"))
        self.assertNotIn("2026-11-20", archive)


if __name__ == "__main__":
    unittest.main()
