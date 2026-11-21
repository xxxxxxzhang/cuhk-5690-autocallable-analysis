import math
import unittest

from src.rates import RateCurve, flat_curve


class RateCurveTests(unittest.TestCase):
    def test_flat_curve_discount_and_forward_rate(self):
        curve = flat_curve(0.04)
        self.assertAlmostEqual(curve.discount_factor(2.0), math.exp(-0.08))
        self.assertAlmostEqual(curve.forward_rate(0.5, 2.0), 0.04)

    def test_interpolation_and_parallel_shift(self):
        curve = RateCurve((1.0, 2.0, 3.0), (0.03, 0.04, 0.05))
        self.assertAlmostEqual(curve.zero_rate(1.5), 0.035)
        shifted = curve.parallel_shift(25)
        self.assertAlmostEqual(shifted.zero_rate(1.5), 0.0375)

    def test_invalid_forward_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            flat_curve(0.04).forward_rate(1.0, 1.0)


if __name__ == "__main__":
    unittest.main()
