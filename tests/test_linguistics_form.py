import unittest
from copy import deepcopy

from pizzabench.linguistics_form import (FormError, PIZZA_KEYS, SIDE_KEYS, compare, empty_pizza, from_ticks,
                                         schema_description, ticked, validate)


class FormTests(unittest.TestCase):
    def test_every_pizza_answers_the_same_options(self):
        form = from_ticks("wheat_dough : category_meats | fig no_sauce no_cheese", "pepperoni")
        self.assertEqual(set(form), {"pizzas"})
        self.assertEqual(len(form["pizzas"]), 2)
        for pizza in form["pizzas"]:
            self.assertEqual(set(pizza) - {"sides"}, set(PIZZA_KEYS))
            for side in pizza["sides"]:
                self.assertEqual(set(side), set(SIDE_KEYS))
        self.assertTrue(form["pizzas"][0]["half_and_half"])
        self.assertEqual(len(form["pizzas"][1]["sides"]), 1)

    def test_validation_rejects_free_text_and_mismatched_halves(self):
        form = from_ticks("pepperoni")
        broken = deepcopy(form)
        broken["pizzas"][0]["note"] = "make it nice"
        with self.assertRaises(FormError):
            validate(broken)
        broken = deepcopy(form)
        broken["pizzas"][0]["half_and_half"] = True
        with self.assertRaises(FormError):
            validate(broken)
        broken = deepcopy(form)
        broken["pizzas"][0]["sides"][0]["pepperoni"] = "yes"
        with self.assertRaises(FormError):
            validate(broken)
        with self.assertRaises(FormError):
            from_ticks("capers")

    def test_slice_count_and_sauce_are_single_choices(self):
        from_ticks("slices_4 : pesto_sauce no_cheese")
        with self.assertRaises(FormError):
            from_ticks("slices_4 no_cut : pepperoni")
        with self.assertRaises(FormError):
            from_ticks("pesto_sauce no_sauce")
        with self.assertRaises(FormError):
            from_ticks("tomato_sauce pesto_sauce")

    def test_compare_ignores_pizza_and_half_order(self):
        expected = from_ticks("category_meats | basil", "pepperoni")
        actual = from_ticks("pepperoni", "basil | category_meats")
        self.assertTrue(compare(expected, actual)["passed"])

    def test_compare_names_the_differing_options(self):
        expected = from_ticks("pepperoni no_cheese")
        result = compare(expected, from_ticks("pepperoni"))
        self.assertFalse(result["passed"])
        self.assertEqual(result["differences"], ["pizza 1 side 1: no_cheese expected True, got False"])
        self.assertIn("number_of_pizzas", compare(expected, from_ticks("pepperoni", "pepperoni"))["differences"][0])
        broken = {"pizzas": [{"note": "x"}]}
        self.assertFalse(compare(expected, broken)["passed"])
        self.assertIsNotNone(compare(expected, broken)["form_error"])

    def test_readable_views(self):
        self.assertEqual(ticked(from_ticks("slices_4 : recipe_hawaiian")),
                         ["pizzas=1", "pizza 1: slices_4 | recipe_hawaiian"])
        self.assertIn("no_cheese", schema_description())
        self.assertEqual(empty_pizza()["sides"][0]["pepperoni"], False)


if __name__ == "__main__":
    unittest.main()
