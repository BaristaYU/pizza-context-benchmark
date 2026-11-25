"""Orders and recipes from the Good Pizza, Great Pizza wiki, and A built from a wiki recipe.

``data/wiki/gpgp_wiki_orders.json`` holds the wiki's order list (List_of_orders) and the
in-game Recipe Book as the wiki lists them. Wiki content is CC BY-SA 3.0; see
``data/wiki/README.md``.

The wiki writes a recipe as ingredients joined by ``+``. ``(...) + (...)`` puts the
ingredients of each group on one half; ``[...]`` is one pizza when there are several, and
``[...] x2`` repeats it. ``Sauce`` means either sauce, ``None`` a bare flatbread. The
recipe does not say how a pizza is cut or baked; those come from the order itself.
"""

from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import re

PATH = Path(__file__).resolve().parents[1] / "data" / "wiki" / "gpgp_wiki_orders.json"
REGULAR_CATEGORIES = ("Fixed recipes", "Named recipes", "Variable Recipes")
TOPPINGS = {
    "Pepperoni": "pepperoni", "Sausage": "sausage", "Mushroom": "mushroom", "Olive": "olive", "Onion": "onion",
    "Bell Pepper": "bell_pepper", "Pineapple": "pineapple", "Basil": "basil", "Eggplant": "eggplant", "Corn": "corn",
    "Garlic": "garlic", "Sliced Tomato": "tomato", "Jalapeno": "jalapeno", "Avocado": "avocado", "Truffle": "truffle",
    "Fig": "fig", "Zucchini": "zucchini", "Artichoke": "artichoke", "Pumpkin": "pumpkin", "Peach": "peach",
    "Apple": "apple", "Duck": "duck", "Bacon": "bacon", "Ham": "ham", "Anchovy": "anchovy", "Shrimp": "shrimp",
    "Chicken": "chicken", "Scallop": "scallop",
}
SAUCES = {"Sauce": "any", "Tomato Sauce": "tomato", "Pesto Sauce": "pesto"}
OTHER = {"Cheese", "Wheat Dough", "None"}


class RecipeError(ValueError):
    """The wiki recipe uses notation or ingredients this benchmark does not model."""


def load(path=PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _split(text):
    parts, depth, current = [], 0, ""
    for ch in text:
        depth += (ch == "(") - (ch == ")")
        if depth < 0:
            raise RecipeError(f"Unbalanced parentheses: {text}")
        if ch == "+" and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if depth:
        raise RecipeError(f"Unbalanced parentheses: {text}")
    parts.append(current.strip())
    if any(not p for p in parts):
        raise RecipeError(f"Empty ingredient in: {text}")
    return parts


def _names(parts):
    for part in parts:
        if part not in TOPPINGS and part not in SAUCES and part not in OTHER:
            raise RecipeError(f"Unknown ingredient: {part}")
    return set(parts)


def _pizza_halves(text):
    """(dough, left items, right items) for one pizza."""
    whole, halves = set(), []
    for part in _split(text):
        if part.startswith("(") and part.endswith(")"):
            halves.append(_names(_split(part[1:-1])))
        else:
            whole |= _names([part])
    if len(halves) > 2:
        raise RecipeError(f"More than two halves: {text}")
    left = whole | (halves[0] if halves else set())
    right = whole | (halves[1] if len(halves) > 1 else set())
    dough = "wheat" if "Wheat Dough" in whole else "regular"
    if "Wheat Dough" in (left ^ right):
        raise RecipeError("Wheat dough on one half")
    return dough, left - {"Wheat Dough", "None"}, right - {"Wheat Dough", "None"}


def pizzas(recipe):
    """Split a recipe into one entry per pizza."""
    recipe = recipe.strip()
    groups = re.findall(r"\[([^\[\]]+)\](?:\s*x(\d+))?", recipe)
    if not groups:
        if "[" in recipe or "]" in recipe:
            raise RecipeError(f"Unsupported recipe: {recipe}")
        return [_pizza_halves(recipe)]
    rest = re.sub(r"\[([^\[\]]+)\](?:\s*x(\d+))?", "", recipe).strip()
    if rest:
        raise RecipeError(f"Unsupported recipe: {recipe}")
    out = []
    for body, times in groups:
        out += [_pizza_halves(body)] * int(times or 1)
    return out


def _region(left, right):
    return "whole" if left and right else "left" if left else "right"


def _variants(dough, left, right, cuts=None, bake=None):
    """A for one pizza; a fixed sauce beside an either-sauce half lists both concrete choices."""
    toppings = sorted({TOPPINGS[t] for t in (left | right) if t in TOPPINGS})
    reverse = {v: k for k, v in TOPPINGS.items()}
    base = {"sauce": [], "cheese": "Cheese" in left or "Cheese" in right, "toppings": toppings,
            "topping_placement": {n: _region(reverse[n] in left, reverse[n] in right) for n in toppings}}
    if base["cheese"]:
        base["cheese_placement"] = _region("Cheese" in left, "Cheese" in right)
    if dough != "regular":
        base["dough"] = dough
    if bake:
        base["bake"] = bake
    if cuts is not None:
        base["cuts"] = cuts
    sauces = []
    for half in (left, right):
        found = [SAUCES[s] for s in half if s in SAUCES]
        if len(found) > 1:
            raise RecipeError("Two sauces on one half")
        sauces.append(found[0] if found else None)
    if all(s in (None, "any") for s in sauces):
        pairs = [tuple(sauces)]
    else:
        pairs = product(*[[s] if s != "any" else ["tomato", "pesto"] for s in sauces])
    results = []
    for pair in pairs:
        pizza = deepcopy(base)
        pizza["sauce"] = sorted({s for s in pair if s is not None})
        if pizza["sauce"]:
            pizza["sauce_placement"] = {s: _region(pair[0] == s, pair[1] == s) for s in pizza["sauce"]}
        if left != right:
            pizza["allow_half_swap"] = True
        results.append(pizza)
    return results


def answer(recipe, *, cuts=None, bake=None):
    """A from a wiki recipe; ``cuts`` and ``bake`` are lists with one value (or None) per pizza."""
    parsed = pizzas(recipe)
    cuts = cuts or [None] * len(parsed)
    bake = bake or [None] * len(parsed)
    if len(cuts) != len(parsed) or len(bake) != len(parsed):
        raise ValueError("cuts and bake need one value per pizza")
    variants = [_variants(d, l, r, c, b) for (d, l, r), c, b in zip(parsed, cuts, bake)]
    answers = [{"pizza_count": len(parsed), "pizzas": list(choice)} for choice in product(*variants)]
    return answers[0] if len(answers) == 1 else {"alternatives": answers}


def regular_orders(data=None):
    """Every (entry, order) pair from the regular order categories with a clarification."""
    data = data or load()
    for index, entry in enumerate(data["entries"]):
        if entry["category"] not in REGULAR_CATEGORIES or entry.get("pairing_uncertain"):
            continue
        for number, order in enumerate(entry["orders"]):
            if order.get("clarification"):
                yield index, number, entry, order


def plain_text(utterance):
    """The wiki quotes each line; Q stores the words without the quotation marks."""
    text = utterance.strip()
    if text.startswith("“") and text.endswith("”"):
        text = text[1:-1]
    return text.strip()
