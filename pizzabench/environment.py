"""Deterministic pizza tools. The GUI and headless runner share this state."""

from copy import deepcopy
from dataclasses import dataclass, field
import math


DEFAULT_REGISTRY = {
    "dough": ["regular", "wheat"],
    "sauce": ["tomato", "pesto"],
    "topping": [
        "pepperoni", "sausage", "mushroom", "olive", "onion", "bell_pepper",
        "pineapple", "anchovy", "bacon", "ham", "shrimp", "corn", "chicken",
        "basil", "tomato", "jalapeno", "garlic", "duck", "fig", "zucchini",
        "artichoke", "avocado", "eggplant", "truffle",
    ],
}
REGIONS = {"whole", "left", "right"}


class ToolError(ValueError):
    """An invalid call leaves the environment unchanged."""


def _positive_integer(value, name):
    if type(value) is not int or value < 1:
        raise ToolError(f"{name} must be a positive integer")
    return value


def topping_points(count, region):
    """Normalized coordinates inside the requested region; no random state."""
    points = []
    visible_count = min(count, 120)
    for index in range(visible_count):
        radius = 0.82 * math.sqrt((index + 0.5) / visible_count)
        angle = index * math.pi * (3 - math.sqrt(5))
        x, y = radius * math.cos(angle), radius * math.sin(angle)
        if region == "left":
            x = -max(abs(x), 0.04)
        elif region == "right":
            x = max(abs(x), 0.04)
        points.append((x, y))
    return points


def _combined_region(regions):
    return "whole" if "whole" in regions or len(regions) > 1 else next(iter(regions))


@dataclass
class Pizza:
    id: int
    dough: str
    spread: bool = False
    phase: int = 0
    sauce: dict = field(default_factory=dict)
    cheese_regions: set = field(default_factory=set)
    toppings: dict = field(default_factory=dict)
    oven_passes: int = 0
    cuts: int = 0
    submitted: bool = False

    @property
    def stage(self):
        if self.submitted:
            return "submitted"
        if self.phase == 6:
            return "cut"
        if self.oven_passes:
            return "baked"
        return "preparation" if self.spread else "dough"

    def snapshot(self):
        counts, placements = {}, {}
        for kind, batches in self.toppings.items():
            regions = {batch["region"] for batch in batches}
            placements[kind] = _combined_region(regions)
            if regions == {"left", "right"}:
                counts[kind] = {
                    side: sum(batch["count"] for batch in batches if batch["region"] == side)
                    for side in ("left", "right")
                }
            else:
                counts[kind] = sum(batch["count"] for batch in batches)
        return {
            "id": self.id,
            "stage": self.stage,
            "dough": self.dough,
            "sauce": sorted(self.sauce),
            "sauce_placement": {
                kind: _combined_region(regions) for kind, regions in sorted(self.sauce.items())
            },
            "cheese": bool(self.cheese_regions),
            "cheese_placement": _combined_region(self.cheese_regions) if self.cheese_regions else "whole",
            "toppings": sorted(self.toppings),
            "topping_counts": counts,
            "topping_placement": placements,
            "bake": {0: None, 1: "normal", 2: "well_done"}[self.oven_passes],
            "cuts": self.cuts,
        }


class PizzaEnvironment:
    version = "0.2"

    def __init__(self, registry=None, initial_state=None):
        self.registry = deepcopy(DEFAULT_REGISTRY if registry is None else registry)
        self.pizzas = {}
        self.trace = []
        self.inventory = {
            item: {kind: 100 for kind in self.registry[item]}
            for item in ("dough", "sauce", "topping")
        }
        self.inventory["cheese"] = 100
        if initial_state is not None:
            self._load_state(initial_state)

    def snapshot(self):
        pizzas = [pizza.snapshot() for pizza in self.pizzas.values()]
        return {
            "inventory": deepcopy(self.inventory),
            "pizza_count": len(pizzas),
            "pizzas": pizzas,
            "submitted": bool(pizzas) and all(pizza.submitted for pizza in self.pizzas.values()),
        }

    def execution(self):
        return {"trace": deepcopy(self.trace), "final_state": self.snapshot()}

    def _load_state(self, state):
        if not isinstance(state, dict) or set(state) != {"inventory", "pizza_count", "pizzas", "submitted"}:
            raise ToolError("S requires inventory, pizza_count, pizzas, and submitted")
        inventory = state["inventory"]
        if not isinstance(inventory, dict) or set(inventory) != {"dough", "sauce", "cheese", "topping"}:
            raise ToolError("inventory requires dough, sauce, cheese, and topping")
        for item in ("dough", "sauce", "topping"):
            stock = inventory[item]
            if not isinstance(stock, dict):
                raise ToolError(f"inventory.{item} must be an object")
            for kind, quantity in stock.items():
                if not isinstance(kind, str) or not kind or (item == "sauce" and kind == "any"):
                    raise ToolError("Inventory must use concrete ingredient IDs")
                if type(quantity) not in (int, float) or not math.isfinite(quantity) or quantity < 0:
                    raise ToolError("Inventory quantities must be finite and nonnegative")
                if item != "sauce" and type(quantity) is not int:
                    raise ToolError("Dough and topping stocks must be integers")
        cheese = inventory["cheese"]
        if type(cheese) not in (int, float) or not math.isfinite(cheese) or cheese < 0:
            raise ToolError("Cheese stock must be finite and nonnegative")
        if not isinstance(state["pizzas"], list) or type(state["pizza_count"]) is not int or state["pizza_count"] != len(state["pizzas"]):
            raise ToolError("S.pizza_count must match S.pizzas")
        self.inventory = deepcopy(inventory)
        self.registry = {item: list(inventory[item]) for item in ("dough", "sauce", "topping")}
        fields = set(Pizza(1, "regular").snapshot())
        for value in state["pizzas"]:
            if not isinstance(value, dict) or set(value) != fields:
                raise ToolError("Each initial pizza must have the observed pizza fields")
            pizza_id = _positive_integer(value["id"], "pizza id")
            if pizza_id in self.pizzas or value["dough"] not in self.registry["dough"]:
                raise ToolError("Initial pizza ID or dough is invalid")
            pizza = Pizza(pizza_id, value["dough"])
            if value["stage"] not in {"dough", "preparation", "baked", "cut", "submitted"}:
                raise ToolError("Invalid pizza stage")
            pizza.spread = value["stage"] != "dough"
            pizza.phase = 1 if pizza.spread else 0
            if not isinstance(value["sauce"], list) or len(set(value["sauce"])) != len(value["sauce"]):
                raise ToolError("Initial sauce kinds must be unique")
            if not isinstance(value["sauce_placement"], dict) or set(value["sauce_placement"]) != set(value["sauce"]):
                raise ToolError("Initial sauce kinds and regions disagree")
            for kind in value["sauce"]:
                region = value["sauce_placement"][kind]
                if kind not in self.registry["sauce"] or region not in REGIONS:
                    raise ToolError("Invalid initial sauce or region")
                pizza.sauce[kind] = {region}
                pizza.phase = 2
            if type(value["cheese"]) is not bool or value["cheese_placement"] not in REGIONS:
                raise ToolError("Invalid initial cheese")
            if value["cheese"]:
                pizza.cheese_regions = {value["cheese_placement"]}
                pizza.phase = 3
            kinds = value["toppings"]
            if not isinstance(kinds, list) or len(set(kinds)) != len(kinds):
                raise ToolError("Initial topping kinds must be unique")
            if set(value["topping_counts"]) != set(kinds) or set(value["topping_placement"]) != set(kinds):
                raise ToolError("Initial topping kinds, counts, and regions disagree")
            for kind in kinds:
                region, count = value["topping_placement"][kind], value["topping_counts"][kind]
                if kind not in self.registry["topping"] or region not in REGIONS:
                    raise ToolError("Invalid initial topping or region")
                batches = []
                if isinstance(count, dict):
                    if not count or not set(count) <= {"left", "right"}:
                        raise ToolError("Invalid half counts")
                    for side, quantity in count.items():
                        _positive_integer(quantity, "topping count")
                        batches.append({"count": quantity, "region": side, "points": topping_points(quantity, side)})
                else:
                    _positive_integer(count, "topping count")
                    batches.append({"count": count, "region": region, "points": topping_points(count, region)})
                if _combined_region({batch["region"] for batch in batches}) != region:
                    raise ToolError("Initial topping counts and region disagree")
                pizza.toppings[kind] = batches
                pizza.phase = 4
            if value["bake"] not in (None, "normal", "well_done"):
                raise ToolError("Invalid initial bake value")
            pizza.oven_passes = {None: 0, "normal": 1, "well_done": 2}[value["bake"]]
            cuts = value["cuts"]
            if type(cuts) is not int or cuts < 0 or cuts == 1:
                raise ToolError("Invalid initial slices")
            pizza.cuts = cuts
            stage = value["stage"]
            if stage in ("dough", "preparation") and (pizza.oven_passes or cuts):
                raise ToolError("An unbaked initial pizza cannot be cut")
            if stage == "dough" and (pizza.sauce or pizza.cheese_regions or pizza.toppings):
                raise ToolError("Unspread dough cannot have ingredients")
            if stage in ("baked", "cut", "submitted"):
                if not pizza.oven_passes or (stage == "baked" and cuts):
                    raise ToolError("Initial stage and baking/cutting disagree")
                pizza.phase = 6 if stage == "cut" or cuts else 5
            pizza.submitted = stage == "submitted"
            self.pizzas[pizza_id] = pizza
        submitted = bool(self.pizzas) and all(pizza.submitted for pizza in self.pizzas.values())
        if type(state["submitted"]) is not bool or state["submitted"] != submitted:
            raise ToolError("S.submitted disagrees with pizza stages")

    def _use_stock(self, item, kind, amount):
        stock = self.inventory["cheese"] if item == "cheese" else self.inventory[item][kind]
        if stock < amount:
            raise ToolError(f"Insufficient {item} stock: {kind or 'cheese'} needs {amount}, has {stock}")
        remaining = stock - amount
        if remaining == int(remaining):
            remaining = int(remaining)
        if item == "cheese":
            self.inventory["cheese"] = remaining
        else:
            self.inventory[item][kind] = remaining

    def tool_definitions(self):
        return {
            "place": {"required": ["pizza", "item"], "optional": ["kind", "region", "count"]},
            "spread": {"required": ["pizza"]},
            "bake": {"required": ["pizza"]},
            "cut": {"required": ["pizza", "slices"]},
            "serve": {"required": ["pizza"]},
            "observe": {"required": []},
        }

    def call(self, tool, args):
        """Execute one call and return its observed result; record failures too."""
        entry = {"tool": deepcopy(tool), "args": deepcopy(args)}
        try:
            if not isinstance(tool, str) or tool not in self.tool_definitions():
                raise ToolError(f"Unknown tool: {tool}")
            if not isinstance(args, dict):
                raise ToolError("args must be an object")
            definition = self.tool_definitions()[tool]
            required = set(definition["required"])
            allowed = required | set(definition.get("optional", []))
            if required - args.keys():
                raise ToolError(f"Missing arguments: {sorted(required - args.keys())}")
            if args.keys() - allowed:
                raise ToolError(f"Unknown arguments: {sorted(args.keys() - allowed)}")
            result = self._execute(tool, args)
        except ToolError as exc:
            entry.update(ok=False, error=str(exc))
            self.trace.append(entry)
            raise
        entry["ok"] = True
        self.trace.append(entry)
        return result

    def _execute(self, tool, args):
        if tool == "observe":
            return self.snapshot()
        pizza_id = _positive_integer(args["pizza"], "pizza")
        if tool == "place":
            self._place(pizza_id, args)
            return self.pizzas[pizza_id].snapshot()
        if pizza_id not in self.pizzas:
            raise ToolError(f"Pizza {pizza_id} has no dough")
        pizza = self.pizzas[pizza_id]
        if pizza.submitted:
            raise ToolError(f"Pizza {pizza_id} has already been served")
        if tool == "spread":
            if pizza.spread:
                raise ToolError("Dough has already been spread")
            pizza.spread = True
            pizza.phase = 1
        elif tool == "bake":
            if not pizza.spread:
                raise ToolError("Spread the dough before baking")
            if pizza.phase == 6:
                raise ToolError("Baking must precede cutting")
            if pizza.oven_passes == 2:
                raise ToolError("This environment supports one or two oven passes")
            pizza.oven_passes += 1
            pizza.phase = 5
        elif tool == "cut":
            slices = args["slices"]
            if type(slices) is not int or slices < 0 or slices == 1:
                raise ToolError("slices must be 0 (uncut) or an integer of at least 2")
            if not pizza.oven_passes:
                raise ToolError("Bake the pizza before cutting")
            if pizza.phase == 6:
                raise ToolError("Pizza has already been cut")
            pizza.cuts = slices
            pizza.phase = 6
        elif tool == "serve":
            if not pizza.oven_passes:
                raise ToolError("Bake the pizza before serving")
            pizza.submitted = True
        return pizza.snapshot()

    def _place(self, pizza_id, args):
        item = args["item"]
        if item not in ("dough", "sauce", "cheese", "topping"):
            raise ToolError("item must be dough, sauce, cheese, or topping")
        expected_keys = {
            "dough": {"pizza", "item", "kind"},
            "sauce": {"pizza", "item", "kind", "region"},
            "cheese": {"pizza", "item", "region"},
            "topping": {"pizza", "item", "kind", "region", "count"},
        }[item]
        if args.keys() != expected_keys:
            raise ToolError(f"place({item}) requires exactly {sorted(expected_keys)}")
        if item != "cheese":
            kind = args["kind"]
            if not isinstance(kind, str) or kind not in self.registry.get(item, []):
                raise ToolError(f"Unavailable {item}: {kind}")
        if item == "dough":
            if pizza_id in self.pizzas:
                raise ToolError(f"Pizza {pizza_id} already has dough")
            self._use_stock("dough", kind, 1)
            self.pizzas[pizza_id] = Pizza(pizza_id, kind)
            return
        region = args["region"]
        if not isinstance(region, str) or region not in REGIONS:
            raise ToolError("region must be whole, left, or right")
        if pizza_id not in self.pizzas:
            raise ToolError(f"Pizza {pizza_id} has no dough")
        pizza = self.pizzas[pizza_id]
        if not pizza.spread:
            raise ToolError("Spread the dough before placing ingredients")
        phase = {"sauce": 2, "cheese": 3, "topping": 4}[item]
        if pizza.submitted or pizza.phase > phase:
            raise ToolError("Follow sauce -> cheese -> toppings -> bake -> cut -> serve")
        if item == "sauce":
            regions = pizza.sauce.get(kind, set())
            if region in regions or "whole" in regions or (region == "whole" and regions):
                raise ToolError("This sauce is already on that region")
            self._use_stock("sauce", kind, 1 if region == "whole" else 0.5)
            pizza.sauce.setdefault(kind, set()).add(region)
        elif item == "cheese":
            regions = pizza.cheese_regions
            if region in regions or "whole" in regions or (region == "whole" and regions):
                raise ToolError("Cheese is already on that region")
            self._use_stock("cheese", None, 1 if region == "whole" else 0.5)
            regions.add(region)
        else:
            count = _positive_integer(args["count"], "count")
            points = topping_points(count, region)
            self._use_stock("topping", kind, count)
            pizza.toppings.setdefault(kind, []).append({"count": count, "region": region, "points": points})
        pizza.phase = phase


def replay(plan, registry=None, initial_state=None):
    """A candidate T is executed without repairing it or filling missing calls."""
    environment = PizzaEnvironment(registry, initial_state)
    if not isinstance(plan, list):
        raise ToolError("T must be an array of calls")
    for index, action in enumerate(plan):
        if not isinstance(action, dict) or set(action) != {"tool", "args"}:
            raise ToolError(f"T[{index}] must contain tool and args")
        environment.call(action["tool"], action["args"])
    return environment
