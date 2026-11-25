import unittest

from pizzabench import wiki_orders
from pizzabench.l_to_a import answer_from_form, same_answer
from pizzabench.linguistics_form import CATEGORIES, RECIPES, from_ticks
from pizzabench.menu import menu


class RecipeTests(unittest.TestCase):
    def test_halves_multiple_pizzas_and_bare_dough(self):
        a = wiki_orders.answer("Sauce + Cheese + (Mushroom) + (Pepperoni + Bell Pepper)")
        pizza = a["pizzas"][0]
        self.assertEqual(pizza["topping_placement"], {"bell_pepper": "right", "mushroom": "left", "pepperoni": "right"})
        self.assertTrue(pizza["allow_half_swap"])
        self.assertEqual(pizza["sauce"], ["any"])
        a = wiki_orders.answer("[Sauce + Cheese + Pepperoni] x2 [Sauce + Cheese + Chicken]")
        self.assertEqual(a["pizza_count"], 3)
        bare = wiki_orders.answer("[Sauce + Cheese] [None]")["pizzas"][1]
        self.assertEqual((bare["sauce"], bare["cheese"], bare["toppings"]), ([], False, []))
        self.assertEqual(wiki_orders.answer("Wheat Dough + Corn")["pizzas"][0]["dough"], "wheat")

    def test_unsupported_recipes_are_rejected(self):
        for recipe in ("House Special", "Anything", "Sauce + Cheese + Rose Petal", "(Sauce) + (Cheese) + (Olive)"):
            with self.assertRaises(wiki_orders.RecipeError):
                wiki_orders.answer(recipe)


class CoverageTests(unittest.TestCase):
    def test_every_wiki_order_can_be_written_on_the_form(self):
        """Every regular wiki recipe this kitchen can make has an ingredient-level L that leads to its A."""
        form_key = {"tomato": "sliced_tomato"}
        checked = 0
        for _, _, entry, _ in wiki_orders.regular_orders():
            try:
                parsed = wiki_orders.pizzas(entry["recipe"])
            except wiki_orders.RecipeError:
                continue
            specs = []
            for dough, left, right in parsed:
                sides = []
                for half in (left, right) if left != right else (left,):
                    ticks = [form_key.get(t, t) for t in (wiki_orders.TOPPINGS[n] for n in half if n in wiki_orders.TOPPINGS)]
                    sauce = [wiki_orders.SAUCES[n] for n in half if n in wiki_orders.SAUCES]
                    ticks += ["no_sauce"] if not sauce else [f"{sauce[0]}_sauce"] if sauce[0] != "any" else []
                    ticks += [] if "Cheese" in half else ["no_cheese"]
                    sides.append(" ".join(ticks))
                specs.append(("wheat_dough : " if dough == "wheat" else "") + " | ".join(sides))
            self.assertTrue(same_answer(answer_from_form(from_ticks(*specs)), wiki_orders.answer(entry["recipe"])),
                            entry["recipe"])
            checked += 1
        self.assertGreater(checked, 600)

    def test_form_names_the_same_recipes_and_categories_as_the_menu(self):
        shop = menu()
        self.assertEqual(set(RECIPES.values()), set(shop["recipes"]))
        self.assertEqual({k[len("category_"):] for k in CATEGORIES}, set(shop["categories"]))


if __name__ == "__main__":
    unittest.main()
