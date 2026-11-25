"""Choose the English 100 from the wiki's regular orders, balanced by order-structure difficulty.

The pool is every order in the wiki's Fixed, Named and Variable recipe sections that has a
clarification line, a recipe this kitchen can make, and no editorial note about a bug or
game strategy. Each order gets A from its wiki recipe, with slicing and double baking read
from the order text and the wiki's note, and the structure tier of that A. A seeded
shuffle then takes one order per wiki recipe until each tier has its quota. Everything
after the quota, in the same shuffled order, is kept as a reserve per tier so that cases
can later be swapped to rebalance the understanding difficulty that annotators label.
"""

import random
import re

from . import wiki_orders
from .structure_difficulty import ocs, tier

SEED = 42
QUOTAS = {"하": 33, "중": 33, "상": 34}
SUPPORTED_CUTS = {None, 0, 2, 4, 8, 18}
EDITORIAL_NOTE = re.compile(r"bugged|impossible|refund|advised|suggested|dismiss|reward|regular dough", re.I)
WORDS = {"two": 2, "four": 4, "eight": 8, "eighteen": 18}
# Orders whose wiki recipe disagrees with the menu or with the order itself, found by
# comparing the recipe with the A that the order's L leads to. Keys are "entry:order".
EXCLUDED = {
    "665:0": "the vegetarian pizza lacks pumpkin, which the wiki's Vegetarian includes elsewhere",
    "512:0": "seafood lacks scallop",
    "626:0": "all meats lacks scallop",
    "681:1": "the vegetarian toppings include bacon",
    "581:0": "tomato sauce on both halves, though the Classic Meat half asks for any sauce",
    "520:1": "the Supreme uses tomato sauce, though the order and the Recipe Book leave the sauce free",
    "666:0": "all meats lacks scallop",
    "35:0": "ham is written for the whole pizza, though the order puts it on one half",
    "624:0": "all meats lacks scallop and all fruits lacks avocado",
}


def slicing_and_baking(order, clarification, note):
    """(cuts, bake) that the order asks for, or None when it leaves them free."""
    text = " ".join(x for x in (order, clarification) if x).lower()
    note = (note or "").lower()
    bake = None
    if re.search(r"oven twice|over twice|bake[sd]? (the )?(pizzas?|flatbread|both pizzas|it|them)? ?twice"
                 r"|cook the (pizza|flatbread) twice", note):
        bake = "well_done"
    elif re.search(r"double[- ]?bak|dark crust|well[- ]done|crispy (pizza|flatbread|crust|dough|pie)|make it crispy"
                   r"|crust as crispy|extra[- ]toast|bake (it|them) twice|twice[- ]baked|burnt|charred", text):
        bake = "well_done"
    cuts = None
    match = re.search(r"cut (?:the pizzas?|each pizza|both pizzas)?\s*(?:only )?(once|twice|four times)", note)
    if match:
        cuts = {"once": 2, "twice": 4, "four times": 8}[match.group(1)]
    match = re.search(r"into (two|four|eight|\d+) slices|in (two) slices", note)
    if match:
        value = match.group(1) or match.group(2)
        cuts = int(value) if value.isdigit() else WORDS[value]
    if "do not cut" in note:
        cuts = 0
    if cuts is None:
        match = re.search(r"\b(\d+|two|four|eight|eighteen)[- ](?:slices|pieces|slice)\b", text)
        halves = re.search(r"cut (?:it )?in half (\w+) times", text)
        times = re.search(r"\bcut (?:it|them|each|each one|all of them|the pizzas?)? ?(once|twice|four times)", text)
        if match:
            value = match.group(1)
            cuts = int(value) if value.isdigit() else WORDS[value]
        elif halves:
            cuts = {"once": 2, "twice": 4, "two": 4, "three": 6, "four": 8}.get(halves.group(2))
        elif times:
            cuts = {"once": 2, "twice": 4, "four times": 8}[times.group(1)]
        elif re.search(r"\bfourths\b", text):
            cuts = 4
        elif re.search(r"don'?t (cut|slice)|uncut|unsliced|no cuts|not cut", text):
            cuts = 0
        elif re.search(r"\bquarter", text):
            cuts = 4
    return (None if cuts == 6 else cuts), bake


def candidates(data=None):
    """Every usable regular order with its A and structure difficulty."""
    data = data or wiki_orders.load()
    for entry_index, order_index, entry, order in wiki_orders.regular_orders(data):
        if order.get("note") and EDITORIAL_NOTE.search(order["note"]):
            continue
        cuts, bake = slicing_and_baking(order["order"], order["clarification"], order.get("note"))
        if cuts not in SUPPORTED_CUTS:
            continue
        try:
            count = len(wiki_orders.pizzas(entry["recipe"]))
            answer = wiki_orders.answer(entry["recipe"], cuts=[cuts] * count, bake=[bake] * count)
        except wiki_orders.RecipeError:
            continue
        score = ocs(answer)
        yield {"key": f"{entry_index}:{order_index}", "entry": entry_index, "order": order_index,
               "category": entry["category"],
               "section": entry["section"], "recipe": entry["recipe"], "note": order.get("note"),
               "order_text": wiki_orders.plain_text(order["order"]),
               "clarification_text": wiki_orders.plain_text(order["clarification"]),
               "cuts": cuts, "bake": bake, "answer": answer,
               "ocs": tier(answer), "ocs_level": score["level"], "ocs_raw": score["raw"]}


def select(pool, quotas=QUOTAS, seed=SEED, dropped=()):
    """(chosen, reserves): one order per wiki recipe, quotas per tier, the rest kept in order.

    ``dropped`` lists orders taken out later, for example to rebalance difficulty; like the
    exclusions they stay in the shuffle, so the next order of the same tier takes their place."""
    skip = set(EXCLUDED) | set(dropped)
    shuffled = list(pool)
    random.Random(seed).shuffle(shuffled)
    chosen, used, reserves = {t: [] for t in quotas}, set(), {t: [] for t in quotas}
    # Excluded orders stay in the shuffle so that excluding one does not reorder the rest.
    for item in shuffled:
        if item["entry"] in used or item["key"] in skip:
            continue
        group = chosen[item["ocs"]]
        if len(group) < quotas[item["ocs"]]:
            group.append(item)
            used.add(item["entry"])
    for item in shuffled:
        if item["entry"] not in used and item["key"] not in skip:
            reserves[item["ocs"]].append(item)
    return chosen, reserves


def interleave(chosen, order=("하", "중", "상")):
    """Round-robin over tiers so that cases 1-50 and 51-100 hold each tier almost equally."""
    queues = {t: list(chosen[t]) for t in order}
    out = []
    while any(queues.values()):
        for t in order:
            if queues[t]:
                out.append(queues[t].pop(0))
    return out
