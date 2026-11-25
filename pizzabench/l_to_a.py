"""A from an L order form and the menu, and an order-insensitive comparison of two A.

This is the reference reasoning for the L-to-A step: named recipes and categories are
expanded with the shop's menu, ``no_*`` options remove toppings, an explicit sauce or
cheese choice overrides what a recipe brings, and the pizza options give dough, baking
and slicing. It also checks the benchmark data: the A that a case's L leads to must equal
the A written from the wiki recipe.
"""

from itertools import product
import json

from . import wiki_orders
from .linguistics_form import CATEGORIES, EXCLUDED_TOPPINGS, RECIPES, TOPPINGS, validate
from .menu import menu as load_menu

SLICES = {"slices_2": 2, "slices_4": 4, "slices_8": 8, "slices_18": 18, "no_cut": 0}
SAUCE_NAMES = {"any": "Sauce", "tomato": "Tomato Sauce", "pesto": "Pesto Sauce"}
WIKI_NAME = {ours: wiki for wiki, ours in wiki_orders.TOPPINGS.items()}
WIKI_NAME["sliced_tomato"] = "Sliced Tomato"  # the form's key; A and the menu call it tomato


def _side(side, shop):
    """The wiki-style item set of one side: sauce, cheese and toppings."""
    sauce, cheese, toppings = "any", True, set()
    for key in RECIPES:
        if side.get(key):
            recipe = shop["recipes"][RECIPES[key]]
            sauce, cheese = recipe["sauce"], recipe["cheese"]
            toppings |= set(recipe["toppings"])
    for key in CATEGORIES:
        if side.get(key):
            name = key[len("category_"):]
            toppings |= {t for t in shop["categories"][name] if t != "cheese"}
            base = shop.get("category_bases", {}).get(name)
            if base:
                sauce, cheese = base["sauce"], base["cheese"]
    toppings |= {key for key in TOPPINGS if side.get(key)}
    for key in EXCLUDED_TOPPINGS:
        if side.get(key):
            name = key[len("no_"):]
            removed = set(shop["categories"][name]) if name in shop["categories"] else {name}
            toppings -= removed
    if side.get("tomato_sauce"):
        sauce = "tomato"
    if side.get("pesto_sauce"):
        sauce = "pesto"
    if side.get("no_sauce"):
        sauce = "none"
    if side.get("no_cheese"):
        cheese = False
    items = {WIKI_NAME[t] for t in toppings}
    if sauce != "none":
        items.add(SAUCE_NAMES[sauce])
    if cheese:
        items.add("Cheese")
    return items


def answer_from_form(form, shop=None):
    """A that one stage of L asks for, given the menu."""
    shop = shop or load_menu()
    validate(form)
    variants = []
    for pizza in form["pizzas"]:
        sides = [_side(side, shop) for side in pizza["sides"]]
        left, right = sides[0], sides[-1]
        cuts = next((n for key, n in SLICES.items() if pizza[key]), None)
        bake = "well_done" if pizza["bake_twice"] else None
        dough = "wheat" if pizza["wheat_dough"] else "regular"
        variants.append(wiki_orders._variants(dough, left, right, cuts, bake))
    answers = [{"pizza_count": len(variants), "pizzas": list(choice)} for choice in product(*variants)]
    return answers[0] if len(answers) == 1 else {"alternatives": answers}


def _mirror(pizza):
    swap = {"left": "right", "right": "left", "whole": "whole"}
    value = json.loads(json.dumps(pizza))
    for key in ("topping_placement", "sauce_placement"):
        if key in value:
            value[key] = {k: swap[v] for k, v in value[key].items()}
    if "cheese_placement" in value:
        value["cheese_placement"] = swap[value["cheese_placement"]]
    return value


def canonical(answer):
    """A as a comparable value: pizza order, half order and alternative order do not matter."""
    options = answer.get("alternatives", [answer])
    return sorted(json.dumps(sorted(min(json.dumps(p, sort_keys=True), json.dumps(_mirror(p), sort_keys=True))
                                    for p in option["pizzas"])) for option in options)


def same_answer(a, b):
    return canonical(a) == canonical(b)
