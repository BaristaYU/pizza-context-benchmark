import json
import unittest
from collections import Counter
from pathlib import Path

from pizzabench.structure_difficulty import ocs, tier

ROOT = Path(__file__).resolve().parents[1]


def pizza(**fields):
    value = {"sauce": ["any"], "cheese": True, "toppings": [], "topping_placement": {},
             "cheese_placement": "whole", "sauce_placement": {"any": "whole"}}
    value.update(fields)
    return value


class StructureDifficultyTests(unittest.TestCase):
    def test_plain_pizza_scores_zero(self):
        self.assertEqual(ocs({"pizzas": [pizza()]})["raw"], 0)
        self.assertEqual(tier({"pizzas": [pizza()]}), "하")

    def test_each_item_follows_the_rules(self):
        half = pizza(toppings=["ham", "olive", "basil"], topping_placement={"ham": "left", "olive": "right"},
                     cheese=False, cuts=4)
        result = ocs({"pizzas": [half, pizza()]})
        self.assertEqual(result["breakdown"], {"pizza_count": 1, "partition": 1, "topping_count": 1,
                                               "special_slots": 2, "different_pizzas": 1})
        self.assertEqual(result["raw"], 6)
        self.assertEqual(result["level"], "O3")

    def test_simplest_alternative_is_used(self):
        busy = {"pizzas": [pizza(toppings=["a", "b", "c", "d", "e", "f"])]}
        self.assertEqual(ocs({"alternatives": [busy, {"pizzas": [pizza()]}]})["raw"], 0)

    def test_english100_spread(self):
        cases = [json.loads(line) for line in
                 (ROOT / "data/english100/benchmark_cases.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(Counter(tier(case["answer"]) for case in cases), {"하": 33, "중": 33, "상": 34})


if __name__ == "__main__":
    unittest.main()
