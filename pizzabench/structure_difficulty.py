"""Order-structure difficulty (OCS) computed from A, following the team's single-instruction-v1 rules.

OCS measures how complex the pizzas to make are, not how the order is worded. It is
therefore a function of A alone and needs no human label. Five items score 0-2 each:

- pizza_count: 1 pizza 0, 2 pizzas 1, 3 or more 2.
- partition: no pizza differs left and right 0; one pizza differs in one state type
  (sauce, cheese or toppings) 1; a pizza differs in two or more types, or two or more
  pizzas are side-specific 2.
- topping_count: distinct toppings on the busiest pizza; 0-2 is 0, 3-5 is 1, 6 or more 2.
  Categories and recipes count after A expands them, because OCS is about what is made.
- special_slots: non-default slot types on one pizza (wheat dough, pesto or no sauce,
  no cheese, baked twice, slices other than 6); 1 is 1, 2 or more 2.
- different_pizzas: identical pizzas 0; different pizzas 1; different pizzas with at
  least two complex pizzas 2. A complex pizza meets two of: side-specific state, three
  or more toppings, a special slot.

Fields that A leaves free count as defaults. When A lists alternatives, the simplest
alternative is used: OCS then means the least structure needed to satisfy the order.
"""

LEVELS = ((1, "O0"), (3, "O1"), (5, "O2"), (7, "O3"), (10, "O4"))
DEFAULT_SAUCES = {"tomato", "any"}


def _sides(pizza):
    """Sauce, cheese and toppings on the left and right halves."""
    def where(placement, default="whole"):
        return {"left": placement in ("whole", "left"), "right": placement in ("whole", "right")}

    state = {}
    for side in ("left", "right"):
        sauces = frozenset(s for s in pizza.get("sauce", ["any"])
                           if where((pizza.get("sauce_placement") or {}).get(s, "whole"))[side])
        cheese = bool(pizza.get("cheese", True)) and where(pizza.get("cheese_placement", "whole"))[side]
        toppings = frozenset(t for t in pizza.get("toppings", [])
                             if where((pizza.get("topping_placement") or {}).get(t, "whole"))[side])
        state[side] = {"sauce": sauces, "cheese": cheese, "toppings": toppings}
    return state


def _special_slots(pizza, state):
    slots = 0
    slots += pizza.get("dough", "regular") != "regular"
    slots += any(not state[s]["sauce"] or not state[s]["sauce"] <= DEFAULT_SAUCES for s in state)
    slots += any(not state[s]["cheese"] for s in state)
    slots += pizza.get("bake", "normal") not in ("normal", None)
    slots += pizza.get("cuts", 6) not in (6, None)
    return slots


def _pizza_scores(pizza):
    state = _sides(pizza)
    differing = sum(state["left"][kind] != state["right"][kind] for kind in ("sauce", "cheese", "toppings"))
    toppings = len(set(pizza.get("toppings", [])))
    slots = _special_slots(pizza, state)
    complex_pizza = sum((differing > 0, toppings >= 3, slots > 0)) >= 2
    return {"differing": differing, "toppings": toppings, "slots": slots, "complex": complex_pizza,
            "signature": repr(sorted((k, repr(v)) for k, v in pizza.items() if k != "allow_half_swap"))}


def _score(order):
    pizzas = [_pizza_scores(p) for p in order["pizzas"]]
    count = len(pizzas)
    side_specific = sum(p["differing"] > 0 for p in pizzas)
    most = max(p["differing"] for p in pizzas)
    partition = 2 if most >= 2 or side_specific >= 2 else 1 if most == 1 else 0
    toppings = max(p["toppings"] for p in pizzas)
    slots = max(p["slots"] for p in pizzas)
    different = len({p["signature"] for p in pizzas}) > 1
    breakdown = {"pizza_count": 0 if count == 1 else 1 if count == 2 else 2,
                 "partition": partition,
                 "topping_count": 0 if toppings <= 2 else 1 if toppings <= 5 else 2,
                 "special_slots": min(slots, 2),
                 "different_pizzas": 0 if not different else 2 if sum(p["complex"] for p in pizzas) >= 2 else 1}
    raw = sum(breakdown.values())
    return {"raw": raw, "level": next(level for top, level in LEVELS if raw <= top), "breakdown": breakdown}


def ocs(answer):
    """OCS of one A; the simplest alternative when A lists several."""
    return min((_score(order) for order in answer.get("alternatives", [answer])), key=lambda s: s["raw"])


# Three levels fitted to the English 100 spread: raw 0-1, 2-3 and 4 or more (39, 47 and 14 orders).
TIERS = {"O0": "하", "O1": "중", "O2": "상", "O3": "상", "O4": "상"}


def tier(answer):
    return TIERS[ocs(answer)["level"]]
