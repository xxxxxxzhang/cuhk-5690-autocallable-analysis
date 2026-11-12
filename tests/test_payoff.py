import unittest
from decimal import Decimal as D
from src.payoff import evaluate_note, load_terms


class PayoffTests(unittest.TestCase):
    def setUp(self):
        self.terms = load_terms()
        self.dates = [r[0] for r in self.terms["schedule"]]
        self.names = self.terms["underlyings"]

    def levels(self, *ratios):
        return {s: D(self.names[s]["initial"]) * D(r) for s, r in zip(self.names, ratios, strict=True)}

    def full_path(self, ratios):
        return {d: self.levels(*ratios) for d in self.dates}

    def test_rising_prices_first_call_only_in_period_two(self):
        path = {d: self.levels(*([str(1 + i / 10)] * 3)) for i, d in enumerate(self.dates, 1)}
        result = evaluate_note(path, self.terms)
        self.assertEqual(result["autocall_date"], self.dates[1])
        self.assertEqual(result["total_cashflow"], D("1078.250"))
        self.assertEqual(len(result["rows"]), 2)

    def test_no_payments_after_call(self):
        path = self.full_path(("1", "1", "1"))
        path[self.dates[2]] = {}
        result = evaluate_note(path, self.terms)
        self.assertEqual(result["coupon_cashflows"], [D("39.125")] * 2)

    def test_memory_recovery_and_reset(self):
        path = self.full_path((".4", ".9", "1"))
        path[self.dates[2]] = self.levels(".8", ".9", "1")
        path[self.dates[3]] = self.levels("1", "1", "1")
        result = evaluate_note(path, self.terms)
        self.assertEqual(result["coupon_cashflows"], list(map(D, ("0", "0", "117.375", "39.125"))))
        self.assertEqual(result["unpaid_memory_coupons"], list(map(D, ("39.125", "78.25", "0", "0"))))

    def test_all_below_barrier(self):
        result = evaluate_note(self.full_path((".35", ".4", ".4")), self.terms)
        self.assertEqual(result["total_cashflow"], D("350"))
        self.assertEqual(sum(result["coupon_cashflows"]), 0)
        self.assertEqual(result["rows"][-1]["expired_periods"], 12)

    def test_best_of_maturity_protection_boundary(self):
        for best, expected in [("1", 1000), (".99", 400)]:
            with self.subTest(best=best):
                path = self.full_path((".4", ".8", best))
                result = evaluate_note(path, self.terms)
                self.assertEqual(result["total_cashflow"], expected)
                self.assertEqual(result["rows"][-1]["status"], "matured")

    def test_published_barriers_and_last_memory_payment(self):
        path = self.full_path((".3", ".9", ".9"))
        path[self.dates[-1]] = {s: D(spec["coupon_barrier"]) for s, spec in self.names.items()}
        result = evaluate_note(path, self.terms)
        self.assertEqual(result["rows"][-1]["cashflow"], D("1469.50"))
        path[self.dates[-1]]["AMZN"] -= D(".01")
        result = evaluate_note(path, self.terms)
        self.assertEqual(result["rows"][-1]["coupon"], 0)
        self.assertLess(result["redemption_amount"], 500)

    def test_maturity_cannot_be_called(self):
        path = self.full_path((".9", ".9", ".9"))
        path[self.dates[-1]] = self.levels("1", "1", "1")
        result = evaluate_note(path, self.terms)
        self.assertIsNone(result["autocall_date"])
        self.assertEqual(result["redemption_amount"], 1000)

    def test_replay_requires_all_past_fixings(self):
        path = {self.dates[0]: self.levels("1", "1", "1")}
        self.assertEqual(evaluate_note(path, self.terms, as_of=self.dates[0])["redemption_amount"], 0)
        with self.assertRaisesRegex(ValueError, "Missing fixing"):
            evaluate_note(path, self.terms)
