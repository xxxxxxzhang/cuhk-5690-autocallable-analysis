import copy
import math
import unittest

from src.model import select_median_path, simulate_paths
from src.payoff import load_terms
from src.valuation import value_paths


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.terms = load_terms()
        self.symbols = list(self.terms["underlyings"])
        self.inputs = {
            "model": "correlated_gbm",
            "risk_free_rate": 0.04,
            "dividend_yields": {symbol: 0.0 for symbol in self.symbols},
            "volatilities": {symbol: 0.20 for symbol in self.symbols},
            "correlation": {
                left: {right: float(left == right) for right in self.symbols}
                for left in self.symbols
            },
            "n_paths": 3,
            "seed": 42,
        }

    def test_same_seed_produces_same_paths(self):
        first = simulate_paths(self.terms, self.inputs)
        second = simulate_paths(self.terms, self.inputs)
        self.assertEqual(first, second)

    def test_shape_and_positive_prices(self):
        paths = simulate_paths(self.terms, self.inputs, n_paths=2)
        expected_dates = [row[0] for row in self.terms["schedule"]]
        self.assertEqual(len(paths), 2)
        self.assertEqual(list(paths[0]), expected_dates)
        for path in paths:
            for prices in path.values():
                self.assertEqual(set(prices), set(self.symbols))
                self.assertTrue(all(value > 0 for value in prices.values()))

    def test_zero_volatility_matches_deterministic_growth(self):
        inputs = copy.deepcopy(self.inputs)
        inputs["volatilities"] = {symbol: 0.0 for symbol in self.symbols}
        path = simulate_paths(self.terms, inputs, n_paths=1)[0]
        first_date = self.terms["schedule"][0][0]
        dt = (
            __import__("datetime").date.fromisoformat(first_date)
            - __import__("datetime").date.fromisoformat(self.terms["pricing_date"])
        ).days / 365.0
        for symbol in self.symbols:
            expected = float(self.terms["underlyings"][symbol]["initial"]) * math.exp(0.04 * dt)
            self.assertAlmostEqual(path[first_date][symbol], expected, places=10)

    def test_invalid_correlation_is_rejected(self):
        inputs = copy.deepcopy(self.inputs)
        inputs["correlation"][self.symbols[0]][self.symbols[1]] = 0.75
        with self.assertRaisesRegex(ValueError, "symmetric"):
            simulate_paths(self.terms, inputs)

    def test_representative_path_is_actual_path_nearest_median(self):
        observations = [row[0] for row in self.terms["schedule"]]

        def constant_path(ratio):
            return {
                observation: {
                    symbol: float(spec["initial"]) * ratio
                    for symbol, spec in self.terms["underlyings"].items()
                }
                for observation in observations
            }

        paths = [constant_path(0.70), constant_path(1.00), constant_path(1.40)]
        selected_index, selected = select_median_path(paths, self.terms)
        self.assertEqual(selected_index, 1)
        self.assertIs(selected, paths[1])

    def test_valuation_matches_known_zero_rate_path(self):
        path = {
            observation: {
                symbol: float(spec["initial"])
                for symbol, spec in self.terms["underlyings"].items()
            }
            for observation, _payment in self.terms["schedule"]
        }
        inputs = {"model": "correlated_gbm", "risk_free_rate": 0.0, "seed": 1}
        summary = value_paths([path], self.terms, inputs)["summary"]
        self.assertAlmostEqual(summary["estimated_value"], 1078.25)


if __name__ == "__main__":
    unittest.main()
