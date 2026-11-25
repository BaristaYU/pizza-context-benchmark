"""Check observed E against A, without turning reference defaults into rules."""

from copy import deepcopy
from functools import lru_cache


def _total(value):
    return sum(value.values()) if isinstance(value, dict) else value


def _quantity_matches(expected, actual):
    if type(expected) is int:
        return _total(actual) == expected
    if not isinstance(expected, dict):
        return False
    if set(expected) <= {"min", "max"} and expected:
        total = _total(actual)
        return expected.get("min", 0) <= total <= expected.get("max", float("inf"))
    if set(expected) <= {"left", "right"} and expected:
        return isinstance(actual, dict) and all(actual.get(side, 0) == count for side, count in expected.items())
    return False


def _swap(pizza):
    swapped = deepcopy(pizza)
    sides = {"left": "right", "right": "left", "whole": "whole"}
    for field in ("sauce_placement", "topping_placement"):
        swapped[field] = {key: sides.get(value, value) for key, value in pizza.get(field, {}).items()}
    if "cheese_placement" in pizza:
        swapped["cheese_placement"] = sides.get(pizza["cheese_placement"], pizza["cheese_placement"])
    for kind, value in pizza.get("topping_counts", {}).items():
        if isinstance(value, dict) and set(value) <= {"left", "right"}:
            swapped["topping_counts"][kind] = {sides[side]: count for side, count in value.items()}
    return swapped


def _pizza_errors(requirements, pizza):
    supported = {
        "dough", "sauce", "sauce_placement", "cheese", "cheese_placement",
        "toppings", "topping_counts", "topping_count", "topping_placement",
        "bake", "cuts", "allow_half_swap",
    }
    errors = [f"Unsupported A field: {field}" for field in requirements if field not in supported]
    for field in ("dough", "cheese", "bake", "cuts"):
        if field in requirements and pizza.get(field) != requirements[field]:
            errors.append(f"{field}: expected {requirements[field]!r}, observed {pizza.get(field)!r}")
    if "sauce" in requirements:
        wanted, observed = set(requirements["sauce"]), set(pizza.get("sauce", []))
        if (wanted == {"any"} and not observed) or (wanted != {"any"} and wanted != observed):
            errors.append(f"sauce: expected {sorted(wanted)}, observed {sorted(observed)}")
    if "toppings" in requirements and set(requirements["toppings"]) != set(pizza.get("toppings", [])):
        errors.append("toppings: missing or additional kinds")
    for kind in requirements.get("toppings", []):
        if _total(pizza.get("topping_counts", {}).get(kind, 0)) < 1:
            errors.append(f"{kind}: requires at least one piece")
    for field in ("sauce_placement", "topping_placement"):
        for kind, region in requirements.get(field, {}).items():
            observed = pizza.get(field, {})
            if field == "sauce_placement" and kind == "any":
                regions = set(observed.values())
                actual = "whole" if "whole" in regions or regions == {"left", "right"} else next(iter(regions), None)
            else:
                actual = observed.get(kind)
            if actual != region:
                errors.append(f"{field}.{kind}: expected {region}, observed {actual}")
    if "cheese_placement" in requirements:
        if not pizza.get("cheese") or pizza.get("cheese_placement") != requirements["cheese_placement"]:
            errors.append("cheese_placement: wrong or absent cheese region")
    for kind, wanted in requirements.get("topping_counts", {}).items():
        actual = pizza.get("topping_counts", {}).get(kind, 0)
        if isinstance(wanted, dict) and set(wanted) <= {"left", "right"} and type(actual) is int:
            region = pizza.get("topping_placement", {}).get(kind)
            if region in ("left", "right"):
                actual = {region: actual}
        if not _quantity_matches(wanted, actual):
            errors.append(f"topping_counts.{kind}: expected {wanted}, observed {actual}")
    if "topping_count" in requirements:
        actual = sum(_total(value) for value in pizza.get("topping_counts", {}).values())
        if not _quantity_matches(requirements["topping_count"], actual):
            errors.append(f"topping_count: observed {actual}")
    return errors


def _matches(requirements, pizza):
    if not _pizza_errors(requirements, pizza):
        return True
    return bool(requirements.get("allow_half_swap")) and not _pizza_errors(_swap(requirements), pizza)


def evaluate(requirements, execution):
    """Outcome score for Planning replay / Execution / E2E; not an L or A scorer."""
    execution = execution.get("final_state", execution)
    if "alternatives" in requirements:
        if not requirements["alternatives"]:
            return {"passed": False, "errors": ["A.alternatives is empty"]}
        results = [evaluate(option, execution) for option in requirements["alternatives"]]
        return next((result for result in results if result["passed"]), {
            "passed": False, "errors": ["No complete A alternative was satisfied"]
        })
    errors = []
    if not execution.get("submitted"):
        errors.append("The order has not been fully submitted")
    observed = execution.get("pizzas", [])
    if execution.get("pizza_count") != len(observed):
        errors.append("E.pizza_count disagrees with E.pizzas")
    if any(pizza.get("stage") != "submitted" for pizza in observed) or not observed:
        errors.append("Every created pizza must be submitted")
    if "pizza_count" in requirements and len(observed) != requirements["pizza_count"]:
        errors.append(f"pizza_count: expected {requirements['pizza_count']}, observed {len(observed)}")
    for key in requirements:
        if key not in {"pizza_count", "pizzas"}:
            errors.append(f"Unsupported A field: {key}")
    wanted = requirements.get("pizzas", [])
    candidates = [[index for index, pizza in enumerate(observed) if _matches(condition, pizza)] for condition in wanted]

    @lru_cache(maxsize=None)
    def match(index, used):
        if index == len(wanted):
            return True
        return any(
            not used & (1 << candidate) and match(index + 1, used | (1 << candidate))
            for candidate in candidates[index]
        )

    if not match(0, 0):
        errors.append("No one-to-one pizza assignment satisfies A")
        for index, condition in enumerate(wanted):
            if not candidates[index] and observed:
                nearest = min((_pizza_errors(condition, pizza) for pizza in observed), key=len)
                errors.extend(f"A.pizzas[{index}]: {message}" for message in nearest)
    return {"passed": not errors, "errors": errors}
