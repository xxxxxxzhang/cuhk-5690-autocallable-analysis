import math
import unittest

from src.stress import run_stress_analysis


class StressAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_stress_analysis()
        cls.rows = {row["scenario"]: row for row in cls.result["scenarios"]}

    def test_factorial_scenarios_are_complete(self):
        self.assertEqual(
            set(self.rows), {
                "legacy_current", "current_regime", "rate_only", "ipo_only", "joint"
            }
        )
        self.assertTrue(all(math.isfinite(row["pv_usd"]) for row in self.rows.values()))

    def test_interaction_decomposition_identity(self):
        interaction = {
            row["metric"]: row["interaction"]
            for row in self.result["interaction"]
        }
        expected = (
            self.rows["joint"]["pv_usd"]
            - self.rows["rate_only"]["pv_usd"]
            - self.rows["ipo_only"]["pv_usd"]
            + self.rows["current_regime"]["pv_usd"]
        )
        self.assertAlmostEqual(interaction["pv_usd"], expected)

    def test_mega_ipo_proxy_is_applied_once_to_current_spots(self):
        current = self.result["current_spots"]
        shock = self.result["event_shock"]
        for symbol in current:
            expected = current[symbol] * (1.0 + shock[symbol])
            self.assertAlmostEqual(self.rows["ipo_only"][f"{symbol}_start"], expected)
            self.assertAlmostEqual(self.rows["joint"][f"{symbol}_start"], expected)

    def test_election_regime_is_not_a_second_spot_shock(self):
        current = self.result["current_spots"]
        for symbol, spot in current.items():
            self.assertAlmostEqual(
                self.rows["legacy_current"][f"{symbol}_start"], spot
            )
            self.assertAlmostEqual(
                self.rows["current_regime"][f"{symbol}_start"], spot
            )

    def test_factorial_scenarios_use_regime_parameters(self):
        self.assertEqual(self.rows["legacy_current"]["parameter_set"], "legacy")
        for scenario in ("current_regime", "rate_only", "ipo_only", "joint"):
            self.assertEqual(self.rows[scenario]["parameter_set"], "regime")


if __name__ == "__main__":
    unittest.main()
