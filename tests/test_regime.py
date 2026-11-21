import unittest

import numpy as np

from src.payoff import load_terms
from src.regime import calibrate_election_regime
from src.model import load_model_inputs


class ElectionRegimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.terms = load_terms()
        cls.symbols = list(cls.terms["underlyings"])
        cls.calibration = calibrate_election_regime(
            load_model_inputs(),
            cls.symbols,
            break_date="2026-11-03",
            as_of="2026-11-20",
            decay=0.90,
            long_run_correlation_weight=0.70,
            recent_correlation_weight=0.30,
        )

    def test_expected_ewma_volatilities(self):
        expected = {
            "AMZN": 0.4506769091,
            "NVDA": 0.9278098899,
            "PLTR": 0.6085188971,
        }
        for symbol, value in expected.items():
            self.assertAlmostEqual(
                self.calibration["volatilities"][symbol], value, places=8
            )

    def test_regime_correlation_is_positive_definite(self):
        matrix = np.asarray([
            [self.calibration["correlation"][left][right]
             for right in self.symbols]
            for left in self.symbols
        ])
        self.assertTrue(np.allclose(matrix, matrix.T))
        self.assertTrue(np.allclose(np.diag(matrix), 1.0))
        self.assertGreater(np.linalg.eigvalsh(matrix).min(), 0.0)

    def test_pre_post_windows_have_equal_return_counts(self):
        counts = {
            row["returns_each_window"]
            for row in self.calibration["comparison_rows"]
        }
        self.assertEqual(counts, {13})

    def test_correlation_shrinkage_weights_must_sum_to_one(self):
        with self.assertRaisesRegex(ValueError, "must sum to one"):
            calibrate_election_regime(
                load_model_inputs(),
                self.symbols,
                break_date="2026-11-03",
                as_of="2026-11-20",
                decay=0.90,
                long_run_correlation_weight=0.80,
                recent_correlation_weight=0.30,
            )


if __name__ == "__main__":
    unittest.main()
