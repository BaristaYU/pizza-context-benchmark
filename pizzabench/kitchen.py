"""Deterministic, coordinate-based kitchen shared by mouse input and tools."""

from copy import deepcopy
from dataclasses import dataclass, field
import math

from .environment import DEFAULT_REGISTRY, ToolError


# Version 3: toppings are placed as a list of points per call, and baking finishes as soon as
# the pizza goes in, landing it on the cutting board. There is no wait or take-out step.
# Version 4: sauce and cheese are recorded only as covered grid cells; the state has no
# scoring profile.
VERSION = "mock-kitchen-4"
MAX_TOPPING_POINTS = 200
EDIBLE_RADIUS = 0.86
BRUSH_RADIUS = 0.16
GRID_STEP = 0.075
COATING_GRID = tuple(
    (round(x * GRID_STEP, 6), round(y * GRID_STEP, 6))
    for y in range(-11, 12) for x in range(-11, 12)
    if math.hypot(x * GRID_STEP, y * GRID_STEP) <= EDIBLE_RADIUS
)
REGION_CELLS = {region: [i for i, (x, _) in enumerate(COATING_GRID) if region == "whole" or (x < 0) == (region == "left")]
                for region in ("whole", "left", "right")}
# Topping guides: a centred 4x4 grid with 0.3 spacing, eight points on each half.
GUIDE_STEP = 0.3
GUIDE_POINTS = tuple((round((i - 1.5) * GUIDE_STEP, 6), round((j - 1.5) * GUIDE_STEP, 6))
                     for j in range(4) for i in range(4))


def number(value, name, minimum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ToolError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ToolError(f"{name} must be at least {minimum}")
    return float(value)


def region_of(points):
    sides = {"left" if x < 0 else "right" for x, _ in points}
    return "whole" if len(sides) != 1 else next(iter(sides))


def cut_angle(start, end):
    """Convert an edge-to-edge drag crossing the center into a diameter cut."""
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1.1 or min(math.hypot(x1, y1), math.hypot(x2, y2)) < 0.65:
        raise ToolError("Drag from one edge of the pizza to the opposite edge")
    if abs(x1 * y2 - y1 * x2) / length > 0.2 or x1 * x2 + y1 * y2 >= 0:
        raise ToolError("The cutter must cross the center of the pizza")
    return math.degrees(math.atan2(dy, dx))


def painted_cells(points, region="whole"):
    """Grid coverage of a stroke, including gaps between mouse events."""
    sampled = [points[0]]
    for a, b in zip(points, points[1:]):
        steps = max(1, math.ceil(math.dist(a, b) / (GRID_STEP / 2)))
        sampled.extend((a[0] + (b[0] - a[0]) * i / steps,
                        a[1] + (b[1] - a[1]) * i / steps) for i in range(1, steps + 1))
    return {i for i, (x, y) in enumerate(COATING_GRID)
            if (region == "whole" or (x < 0) == (region == "left")) and
            any((x - px) ** 2 + (y - py) ** 2 <= BRUSH_RADIUS ** 2 for px, py in sampled)}


@dataclass
class KitchenPizza:
    id: int
    dough: str
    location: str = "preparation"
    spread: bool = False
    coatings: dict = field(default_factory=dict)
    pieces: list = field(default_factory=list)
    oven_passes: int = 0
    cut_angles: list = field(default_factory=list)
    history: list = field(default_factory=list)

    def snapshot(self):
        counts, placements = {}, {}
        for kind in sorted({p["kind"] for p in self.pieces}):
            points = [(p["x"], p["y"]) for p in self.pieces if p["kind"] == kind]
            counts[kind] = {side: sum((x < 0) == (side == "left") for x, _ in points)
                            for side in ("left", "right")}
            placements[kind] = region_of(points)
        sauces = sorted(k for k, cells in self.coatings.items() if k != "cheese" and cells)
        cheese = self.coatings.get("cheese", [])
        unique_angles = []
        for raw_angle in self.cut_angles:
            angle = raw_angle % 180
            if not any(min(abs(angle - a), 180 - abs(angle - a)) < 0.01 for a in unique_angles):
                unique_angles.append(angle)
        stage = self.location
        if stage == "preparation" and not self.spread:
            stage = "dough"
        return {
            "id": self.id, "stage": stage, "location": self.location, "dough": self.dough,
            "spread": self.spread, "sauce": sauces,
            "sauce_placement": {k: region_of([COATING_GRID[i] for i in self.coatings[k]]) for k in sauces},
            "cheese": bool(cheese),
            "cheese_placement": region_of([COATING_GRID[i] for i in cheese]) if cheese else "whole",
            "toppings": sorted(counts), "topping_counts": counts,
            "topping_placement": placements,
            "bake": None if not self.oven_passes else (
                "normal" if self.oven_passes == 1 else "well_done" if self.oven_passes == 2 else "overcooked"),
            "oven_passes": self.oven_passes,
            "cuts": 2 * len(unique_angles), "cut_angles": list(self.cut_angles),
            "pieces": deepcopy(self.pieces), "coatings": deepcopy(self.coatings),
            "history": deepcopy(self.history),
        }


class Kitchen:
    """Time advances only through advance()/wait, so API runs can be replayed."""

    version = VERSION
    ACTIONS = {
        "create": ({"dough"}, set()), "spread": ({"pizza"}, set()),
        "paint": ({"pizza", "item", "points"}, {"kind", "region"}),
        "fill": ({"pizza", "item"}, {"kind", "region"}),
        "place_toppings": ({"pizza", "kind", "points"}, set()),
        "bake": ({"pizza"}, set()), "cut": ({"pizza", "angle"}, set()),
        "serve": ({"pizza"}, set()), "undo": ({"pizza"}, set()),
        "discard": ({"pizza"}, set()), "observe": (set(), set()),
    }

    def __init__(self, *, oven_seconds=6, workbench_capacity=3, inventory=None):
        self.oven_seconds = number(oven_seconds, "oven_seconds", 0.1)
        if type(workbench_capacity) is not int or workbench_capacity < 1:
            raise ToolError("workbench_capacity must be a positive integer")
        self.workbench_capacity = workbench_capacity
        self.registry = deepcopy(DEFAULT_REGISTRY)
        self.inventory = {item: {kind: 100 for kind in self.registry[item]}
                          for item in ("dough", "sauce", "topping")}
        self.inventory["cheese"] = 100
        if inventory is not None:
            self._validate_inventory(inventory)
            self.inventory = deepcopy(inventory)
            self.registry = {k: list(inventory[k]) for k in ("dough", "sauce", "topping")}
        self.pizzas = {}
        self.next_id = 1
        self.time = 0.0
        self.oven_active = None
        self.oven_remaining = 0.0
        self.oven_queue = []
        self.trace = []

    @staticmethod
    def _validate_inventory(inventory):
        if not isinstance(inventory, dict) or set(inventory) != {"dough", "sauce", "topping", "cheese"}:
            raise ToolError("Invalid inventory categories")
        for item, stock in inventory.items():
            if item == "cheese":
                number(stock, "cheese stock", 0)
                continue
            if not isinstance(stock, dict) or not stock:
                raise ToolError(f"Invalid {item} inventory")
            for kind, quantity in stock.items():
                if not isinstance(kind, str) or not kind or kind == "any":
                    raise ToolError("Inventory needs concrete ingredient names")
                number(quantity, "stock", 0)
                if item != "sauce" and type(quantity) is not int:
                    raise ToolError("Dough and toppings use integer stocks")

    def snapshot(self):
        return {
            "environment_version": VERSION,
            "config": {"oven_seconds": self.oven_seconds, "workbench_capacity": self.workbench_capacity},
            "time": self.time, "next_pizza_id": self.next_id,
            "inventory": deepcopy(self.inventory), "pizza_count": len(self.pizzas),
            "pizzas": [p.snapshot() for p in self.pizzas.values()],
            "oven": {"active": self.oven_active, "remaining": self.oven_remaining, "queue": list(self.oven_queue)},
            "submitted": bool(self.pizzas) and all(p.location == "submitted" for p in self.pizzas.values()),
        }

    @classmethod
    def from_state(cls, state):
        if not isinstance(state, dict) or state.get("environment_version") != VERSION:
            raise ToolError("Unsupported kitchen state version")
        try:
            kitchen = cls(**state["config"], inventory=state["inventory"])
            kitchen.time = number(state["time"], "time", 0)
            kitchen.next_id = state["next_pizza_id"]
            if type(kitchen.next_id) is not int or kitchen.next_id < 1:
                raise ToolError("Invalid next pizza ID")
            for value in state["pizzas"]:
                raw = {key: deepcopy(value[key]) for key in KitchenPizza.__dataclass_fields__}
                pizza = KitchenPizza(**raw)
                if type(pizza.id) is not int or not 0 < pizza.id < kitchen.next_id or pizza.id in kitchen.pizzas:
                    raise ToolError("Invalid pizza ID")
                if pizza.dough not in kitchen.registry["dough"] or type(pizza.spread) is not bool:
                    raise ToolError("Invalid dough")
                if pizza.location not in {"preparation", "queued", "baking", "oven_ready", "cutting", "submitted"}:
                    raise ToolError("Invalid pizza location")
                if type(pizza.oven_passes) is not int or pizza.oven_passes < 0:
                    raise ToolError("Invalid bake count")
                for piece in pizza.pieces:
                    kitchen._point(piece["x"], piece["y"], edible=True)
                    if piece["kind"] not in kitchen.registry["topping"]:
                        raise ToolError("Unknown topping")
                for kind, cells in pizza.coatings.items():
                    if kind not in [*kitchen.registry["sauce"], "cheese"] or cells != sorted(set(cells)):
                        raise ToolError("Invalid coating")
                    if any(type(i) is not int or not 0 <= i < len(COATING_GRID) for i in cells):
                        raise ToolError("Invalid coating coordinates")
                for angle in pizza.cut_angles:
                    number(angle, "cut angle")
                kitchen.pizzas[pizza.id] = pizza
            oven = state["oven"]
            kitchen.oven_active = oven["active"]
            kitchen.oven_remaining = number(oven["remaining"], "oven remaining", 0)
            kitchen.oven_queue = list(oven["queue"])
            queued = [p.id for p in kitchen.pizzas.values() if p.location == "queued"]
            if len(set(kitchen.oven_queue)) != len(kitchen.oven_queue) or set(queued) != set(kitchen.oven_queue):
                raise ToolError("Oven queue disagrees with pizzas")
            active = [p for p in kitchen.pizzas.values() if p.location in {"baking", "oven_ready"}]
            if len(active) > 1 or [p.id for p in active] != ([] if kitchen.oven_active is None else [kitchen.oven_active]):
                raise ToolError("Oven occupancy disagrees with pizzas")
            if (kitchen.oven_remaining > 0) != bool(active and active[0].location == "baking"):
                raise ToolError("Oven progress disagrees with pizzas")
            if kitchen.oven_remaining > kitchen.oven_seconds:
                raise ToolError("Invalid oven progress")
            if kitchen.snapshot() != state:
                raise ToolError("State fields disagree with physical pizza data")
            return kitchen
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            if isinstance(exc, ToolError):
                raise
            raise ToolError("Malformed kitchen state") from exc

    def execution(self):
        return {"trace": deepcopy(self.trace), "final_state": self.snapshot()}

    def tool_definitions(self):
        return {name: {"required": sorted(required), "optional": sorted(optional)}
                for name, (required, optional) in self.ACTIONS.items()}

    def call(self, tool, args=None):
        args = {} if args is None else args
        entry = {"step": len(self.trace) + 1, "time": self.time, "tool": tool, "args": deepcopy(args)}
        before = deepcopy({key: value for key, value in self.__dict__.items() if key != "trace"})
        try:
            if not isinstance(tool, str) or tool not in self.ACTIONS or not isinstance(args, dict):
                raise ToolError("Unknown tool or invalid arguments")
            required, optional = self.ACTIONS[tool]
            if required - args.keys() or args.keys() - required - optional:
                raise ToolError(f"{tool} needs {sorted(required)}; optional: {sorted(optional)}")
            result = self._execute(tool, args)
            entry.update(ok=True, result=deepcopy(result))
        except ToolError as exc:
            self.__dict__.update(before)
            entry.update(ok=False, error=str(exc))
            self.trace.append(entry)
            raise
        self.trace.append(entry)
        return result

    def _pizza(self, pizza_id):
        if type(pizza_id) is not int or pizza_id not in self.pizzas:
            raise ToolError("Select an existing pizza")
        pizza = self.pizzas[pizza_id]
        if pizza.location == "submitted":
            raise ToolError("This pizza has already been served")
        return pizza

    def _preparation(self, pizza):
        if pizza.location != "preparation" or not pizza.spread:
            raise ToolError("Ingredients can only be added to spread dough at the preparation board")

    def _stock(self, item, kind, delta):
        current = self.inventory["cheese"] if item == "cheese" else self.inventory[item][kind]
        if current + 1e-9 < delta:
            raise ToolError(f"Insufficient {item} stock")
        remaining = max(0, current - delta)
        remaining = round(remaining, 10) if item in {"cheese", "sauce"} else remaining
        if item == "cheese":
            self.inventory["cheese"] = remaining
        else:
            self.inventory[item][kind] = remaining

    @staticmethod
    def _point(x, y, *, edible=False):
        x, y = number(x, "x"), number(y, "y")
        if edible and math.hypot(x, y) > EDIBLE_RADIUS + 1e-6:
            raise ToolError("Place toppings inside the pizza")
        if max(abs(x), abs(y)) > 2:
            raise ToolError("Coordinates are outside the workspace")
        return round(x, 6), round(y, 6)

    def _start_next(self):
        if self.oven_active is None and self.oven_queue:
            self.oven_active = self.oven_queue.pop(0)
            self.pizzas[self.oven_active].location = "baking"
            self.oven_remaining = self.oven_seconds

    def advance(self, seconds):
        seconds = number(seconds, "seconds", 0)
        self.time = round(number(self.time + seconds, "elapsed time", 0), 6)
        if self.oven_active is not None and self.oven_remaining > 0:
            self.oven_remaining = round(max(0.0, self.oven_remaining - seconds), 6)
            if self.oven_remaining == 0:
                pizza = self.pizzas[self.oven_active]
                pizza.oven_passes += 1
                pizza.location = "oven_ready"

    def _execute(self, tool, args):
        if tool == "observe":
            return self.snapshot()
        if tool == "create":
            kind = args["dough"]
            if not isinstance(kind, str) or kind not in self.registry["dough"]:
                raise ToolError("Choose available regular or wheat dough")
            if sum(p.location == "preparation" for p in self.pizzas.values()) >= self.workbench_capacity:
                raise ToolError("The preparation board is full")
            self._stock("dough", kind, 1)
            pizza = KitchenPizza(self.next_id, kind)
            self.pizzas[pizza.id] = pizza
            self.next_id += 1
            return pizza.snapshot()
        pizza = self._pizza(args["pizza"])
        if tool == "spread":
            if pizza.location != "preparation" or pizza.spread:
                raise ToolError("Select unspread dough at the preparation board")
            pizza.spread = True
        elif tool == "place_toppings":
            self._preparation(pizza)
            kind = args["kind"]
            if not isinstance(kind, str) or kind not in self.registry["topping"]:
                raise ToolError("This topping is unavailable")
            points = args["points"]
            if not isinstance(points, list) or not 1 <= len(points) <= MAX_TOPPING_POINTS:
                raise ToolError(f"points needs 1..{MAX_TOPPING_POINTS} coordinates")
            placed = []
            for point in points:
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise ToolError("Each topping point needs x and y")
                placed.append(self._point(*point, edible=True))
            self._stock("topping", kind, len(placed))
            pizza.pieces.extend({"kind": kind, "x": x, "y": y} for x, y in placed)
            # One call is one action, so undo removes the whole set placed here.
            pizza.history.append({"action": "topping", "kind": kind, "count": len(placed)})
        elif tool in {"paint", "fill"}:
            self._preparation(pizza)
            item = args["item"]
            if not isinstance(item, str) or item not in {"sauce", "cheese"}:
                raise ToolError("The brush applies sauce or cheese")
            kind = args.get("kind")
            if item == "sauce" and (not isinstance(kind, str) or kind not in self.registry["sauce"]):
                raise ToolError("Sauce needs kind: " + " or ".join(self.registry["sauce"]))
            if item == "cheese" and kind is not None:
                raise ToolError("Cheese takes no kind; omit kind for cheese")
            region = args.get("region", "whole")
            if not isinstance(region, str) or region not in {"whole", "left", "right"}:
                raise ToolError("region must be whole, left or right")
            if tool == "paint":
                points = args["points"]
                if not isinstance(points, list) or not 1 <= len(points) <= 2048:
                    raise ToolError("A stroke needs 1..2048 coordinates")
                checked = []
                for point in points:
                    if not isinstance(point, (list, tuple)) or len(point) != 2:
                        raise ToolError("Each brush point needs x and y")
                    checked.append(self._point(*point))
                covered = painted_cells(checked, region)
            else:
                covered = set(REGION_CELLS[region])
            key = kind if item == "sauce" else "cheese"
            cells = set(pizza.coatings.get(key, []))
            added = sorted(covered - cells)
            if added:
                cost = len(added) / len(COATING_GRID)
                self._stock(item, kind, cost)
                pizza.coatings[key] = sorted(cells | set(added))
                pizza.history.append({"action": "paint", "item": item, "kind": kind, "key": key,
                                      "added": added, "cost": cost})
        elif tool == "undo":
            self._preparation(pizza)
            if not pizza.history:
                raise ToolError("There is no ingredient action to undo")
            last = pizza.history.pop()
            if last["action"] == "topping":
                count = last.get("count", 1)
                del pizza.pieces[-count:]
                self._stock("topping", last["kind"], -count)
            else:
                cells = sorted(set(pizza.coatings[last["key"]]) - set(last["added"]))
                if cells:
                    pizza.coatings[last["key"]] = cells
                else:
                    del pizza.coatings[last["key"]]
                self._stock(last["item"], last["kind"], -last["cost"])
        elif tool == "bake":
            # Baking time has no effect on the result, so one bake is one finished pass that
            # lands on the cutting board. A pizza on the board can go back for a second pass.
            if not pizza.spread or pizza.location not in {"preparation", "cutting"}:
                raise ToolError("Spread the dough and select a pizza ready for the oven")
            if any(p.location == "cutting" and p.id != pizza.id for p in self.pizzas.values()):
                raise ToolError("Serve or discard the pizza on the cutting board first")
            if pizza.location == "preparation":
                pizza.history.clear()
            pizza.oven_passes += 1
            pizza.location = "cutting"
            self.time = round(self.time + self.oven_seconds, 6)
        elif tool == "cut":
            if pizza.location != "cutting":
                raise ToolError("Bake the pizza before cutting it")
            pizza.cut_angles.append(round(number(args["angle"], "angle"), 6))
        elif tool == "serve":
            if pizza.location != "cutting" or not pizza.oven_passes:
                raise ToolError("Bake the pizza before serving it")
            pizza.location = "submitted"
        elif tool == "discard":
            if pizza.location == "baking":
                raise ToolError("Wait for the oven before discarding this pizza")
            self.oven_queue = [i for i in self.oven_queue if i != pizza.id]
            if self.oven_active == pizza.id:
                self.oven_active = None
                self.oven_remaining = 0
                self._start_next()
            del self.pizzas[pizza.id]
            return {"discarded": pizza.id}
        return pizza.snapshot()


INTERNAL_PIZZA_FIELDS = ("coatings", "history")


def coverage(cells):
    """Share of each region covered by one coating, from the internal grid cells."""
    painted = set(cells)
    return {region: round(len(painted.intersection(indices)) / len(indices), 3)
            for region, indices in REGION_CELLS.items()}


def observable_state(value):
    """The S that clients see: pizza state with coating coverage instead of internal grids.

    The kitchen keeps the painted grid cells and the undo history to restore and undo.
    They are not part of S: the grid cells become a coverage share per region, and the
    undo history is an action log.
    """
    if isinstance(value, list):
        return [observable_state(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "pizzas" in value and "oven" in value:
        value = {key: item for key, item in value.items() if key != "oven"}
    if "pieces" in value and "coatings" in value:
        state = {key: observable_state(item) for key, item in value.items() if key not in INTERNAL_PIZZA_FIELDS}
        state["coverage"] = {name: coverage(cells) for name, cells in sorted((value["coatings"] or {}).items()) if cells}
        return state
    return {key: observable_state(item) for key, item in value.items()}
