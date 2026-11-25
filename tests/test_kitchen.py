from copy import deepcopy
import json
from pathlib import Path
import unittest

from pizzabench.environment import ToolError
from pizzabench.game import GameSession, run_plan
from pizzabench.game_orders import load_orders
from pizzabench.kitchen import COATING_GRID, GUIDE_POINTS, Kitchen, cut_angle


def dough(kitchen, kind="regular"):
    pizza_id = kitchen.call("create", {"dough": kind})["id"]
    kitchen.call("spread", {"pizza": pizza_id})
    return pizza_id


def paint(kitchen, pizza_id, item, *, kind=None, region="whole"):
    args = {"pizza": pizza_id, "item": item, "region": region,
            "points": [[x, y] for x, y in COATING_GRID if region == "whole" or (x < 0) == (region == "left")]}
    if kind is not None:
        args["kind"] = kind
    kitchen.call("paint", args)


def bake_and_take(kitchen, pizza_id):
    kitchen.call("bake", {"pizza": pizza_id})


class KitchenTests(unittest.TestCase):
    def test_guides_have_eight_positions_per_half(self):
        self.assertEqual(len(GUIDE_POINTS), 16)
        self.assertEqual(sum(x < 0 for x, _ in GUIDE_POINTS), 8)

    def test_exact_geometry_survives_json_restore_and_replay(self):
        k = Kitchen()
        p = dough(k)
        for x, y in [(-.71, .05), (.33, -.17), (0, .72)]:
            k.call("place_toppings", {"pizza": p, "kind": "olive", "points": [[x, y]]})
        paint(k, p, "sauce", kind="pesto", region="left")
        state = json.loads(json.dumps(k.snapshot()))
        restored = Kitchen.from_state(state)
        self.assertEqual(restored.snapshot(), state)
        self.assertEqual(restored.pizzas[p].pieces[0]["x"], -.71)
        replayed = Kitchen()
        for action in k.trace:
            replayed.call(action["tool"], action["args"])
        self.assertEqual(k.snapshot(), replayed.snapshot())

    def test_coatings_and_piece_counts_keep_independent_halves(self):
        k = Kitchen()
        p = dough(k)
        paint(k, p, "sauce", kind="tomato", region="left")
        paint(k, p, "sauce", kind="pesto", region="right")
        paint(k, p, "cheese", region="left")
        for x in [-.5, -.3, .4]:
            k.call("place_toppings", {"pizza": p, "kind": "onion", "points": [[x, .2]]})
        value = k.pizzas[p].snapshot()
        self.assertEqual(value["sauce_placement"], {"tomato": "left", "pesto": "right"})
        self.assertEqual(value["cheese_placement"], "left")
        self.assertEqual(value["topping_counts"]["onion"], {"left": 2, "right": 1})
        self.assertEqual(value["topping_placement"]["onion"], "whole")

    def test_ingredient_order_is_free_within_preparation(self):
        k = Kitchen()
        p = dough(k)
        k.call("place_toppings", {"pizza": p, "kind": "olive", "points": [[.3, 0]]})
        paint(k, p, "cheese")
        paint(k, p, "sauce", kind="tomato")
        self.assertEqual(k.pizzas[p].snapshot()["sauce"], ["tomato"])

    def test_invalid_actions_are_atomic_and_recoverable(self):
        k = Kitchen()
        p = dough(k)
        before = k.snapshot()
        invalid = [
            ("place_toppings", {"pizza": p, "kind": "olive", "points": [[1, 1]]}),
            ("place_toppings", {"pizza": p, "kind": "olive", "points": [[0, 0], [1, 1]]}),
            ("place_toppings", {"pizza": p, "kind": "olive", "points": []}),
            ("place_toppings", {"pizza": True, "kind": "olive", "points": [[0, 0]]}),
            ("paint", {"pizza": p, "item": [], "points": [[0, 0]]}),
            ("paint", {"pizza": p, "item": "cheese", "points": [[0, 0], [float("nan"), 0]]}),
            ("wait", {"seconds": 1}),
            ("take_out", {"pizza": p}),
            ("cut", {"pizza": p, "angle": 0}),
        ]
        for tool, args in invalid:
            with self.subTest(tool=tool, args=args), self.assertRaises(ToolError):
                k.call(tool, args)
            self.assertEqual(before, k.snapshot())
            self.assertFalse(k.trace[-1]["ok"])
        k.call("place_toppings", {"pizza": p, "kind": "olive", "points": [[-.3, 0]]})
        self.assertEqual(len(k.pizzas[p].pieces), 1)

    def test_stock_and_undo_only_affect_the_target_pizza(self):
        k = Kitchen()
        p, other = dough(k), dough(k)
        paint(k, p, "cheese")
        self.assertAlmostEqual(k.inventory["cheese"], 99)
        k.call("place_toppings", {"pizza": other, "kind": "olive", "points": [[-.2, 0]]})
        k.call("undo", {"pizza": p})
        self.assertAlmostEqual(k.inventory["cheese"], 100)
        self.assertEqual(k.inventory["topping"]["olive"], 99)
        self.assertEqual(len(k.pizzas[other].pieces), 1)
        k.inventory["topping"]["olive"] = 0
        before = k.snapshot()
        with self.assertRaises(ToolError):
            k.call("place_toppings", {"pizza": p, "kind": "olive", "points": [[0, 0]]})
        self.assertEqual(k.snapshot(), before)

    def test_painting_over_the_same_area_does_not_charge_twice(self):
        k = Kitchen()
        p = dough(k)
        paint(k, p, "sauce", kind="tomato")
        state = k.snapshot()
        paint(k, p, "sauce", kind="tomato")
        self.assertEqual(k.snapshot(), state)

    def test_fast_brush_stroke_fills_between_events(self):
        k = Kitchen()
        p = dough(k)
        k.call("paint", {"pizza": p, "item": "cheese", "points": [[-.6, 0], [.6, 0]]})
        indices = k.pizzas[p].coatings["cheese"]
        self.assertTrue(any(abs(COATING_GRID[i][0]) < .05 and abs(COATING_GRID[i][1]) < .05 for i in indices))

    def test_bake_finishes_at_once_and_the_cutting_board_holds_one_pizza(self):
        k = Kitchen(oven_seconds=2)
        p, other = dough(k), dough(k)
        k.call("bake", {"pizza": p})
        self.assertEqual((k.pizzas[p].location, k.pizzas[p].oven_passes), ("cutting", 1))
        self.assertEqual(k.time, 2)
        with self.assertRaises(ToolError):
            k.call("bake", {"pizza": other})
        restored = Kitchen.from_state(json.loads(json.dumps(k.snapshot())))
        restored.call("serve", {"pizza": p})
        restored.call("bake", {"pizza": other})
        self.assertEqual(restored.pizzas[other].location, "cutting")

    def test_one_call_places_many_toppings_and_undo_removes_them_together(self):
        k = Kitchen()
        p = dough(k)
        k.call("place_toppings", {"pizza": p, "kind": "olive", "points": [[-.3, 0], [.3, 0], [0, .4]]})
        self.assertEqual(k.pizzas[p].snapshot()["topping_counts"]["olive"], {"left": 1, "right": 2})
        self.assertEqual(k.inventory["topping"]["olive"], 97)
        k.call("undo", {"pizza": p})
        self.assertEqual(k.pizzas[p].pieces, [])
        self.assertEqual(k.inventory["topping"]["olive"], 100)

    def test_rebaking_supports_well_done_and_overcooked_states(self):
        k = Kitchen(oven_seconds=1)
        p = dough(k)
        for passes in range(1, 4):
            k.call("bake", {"pizza": p})
            self.assertEqual(k.pizzas[p].oven_passes, passes)
        self.assertEqual(k.pizzas[p].snapshot()["bake"], "overcooked")
        with self.assertRaises(ToolError):
            k.call("place_toppings", {"pizza": p, "kind": "olive", "points": [[0, 0]]})

    def test_actual_cut_angles_and_duplicate_lines(self):
        k = Kitchen()
        p = dough(k)
        bake_and_take(k, p)
        for angle in [0, 60, 120, 180]:
            k.call("cut", {"pizza": p, "angle": angle})
        self.assertEqual(k.pizzas[p].snapshot()["cuts"], 6)
        self.assertEqual(k.pizzas[p].cut_angles, [0, 60, 120, 180])
        self.assertAlmostEqual(cut_angle((-.9, 0), (.9, 0)), 0)
        self.assertAlmostEqual(cut_angle((0, -.9), (0, .9)), 90)
        for start, end in [((0, 0), (.9, 0)), ((-.9, .7), (.9, .7)), ((.7, 0), (.8, 0))]:
            with self.assertRaises(ToolError):
                cut_angle(start, end)

    def test_restoration_rejects_inconsistent_or_nonfinite_state(self):
        k = Kitchen()
        p = dough(k)
        for change in (lambda s: s.update(time=float("nan")),
                       lambda s: s["oven"].update(active=p),
                       lambda s: s["pizzas"][0].update(cuts=6)):
            state = deepcopy(k.snapshot())
            change(state)
            with self.assertRaises(ToolError):
                Kitchen.from_state(state)

    def test_clarification_reset_and_hidden_reference(self):
        session = GameSession(load_orders()[0])
        self.assertNotIn("answer", session.observe())
        self.assertNotIn("clarification_text", session.observe()["question"])
        session.call("clarify", {})
        self.assertIn("clarification_text", session.observe()["question"])
        session.reset()
        self.assertFalse(session.clarified)
        self.assertEqual(session.kitchen.trace, [])
        self.assertNotIn("clarification_text", session.observe()["question"])

    def test_complete_coordinate_plan_grades_and_replays(self):
        plan = [
            {"tool": "create", "args": {"dough": "regular"}},
            {"tool": "spread", "args": {"pizza": 1}},
            {"tool": "paint", "args": {"pizza": 1, "item": "sauce", "kind": "tomato", "points": [[0, 0]]}},
            {"tool": "paint", "args": {"pizza": 1, "item": "cheese", "points": [[0, 0]]}},
            {"tool": "place_toppings", "args": {"pizza": 1, "kind": "olive", "points": [[-.4, .2]]}},
            {"tool": "bake", "args": {"pizza": 1}},
            *[{"tool": "cut", "args": {"pizza": 1, "angle": a}} for a in [0, 60, 120]],
            {"tool": "serve", "args": {"pizza": 1}},
        ]
        result = run_plan(load_orders()[0], plan)
        self.assertTrue(result["score"]["passed"])
        again = run_plan(load_orders()[0], [{"tool": r["tool"], "args": r["args"]} for r in result["execution"]["trace"]])
        self.assertEqual(result, again)
        wrong = deepcopy(plan)
        wrong[4]["args"]["kind"] = "mushroom"
        self.assertFalse(run_plan(load_orders()[0], wrong)["score"]["passed"])

    def test_existing_ten_orders_can_be_made_with_coordinate_tools(self):
        source = Path(__file__).resolve().parents[1] / "data/samples/benchmark_cases_fixed_recipes.jsonl"
        for line in source.read_text(encoding="utf-8").splitlines():
            case = json.loads(line)
            with self.subTest(case=case["id"]):
                session = GameSession(case)
                k = session.kitchen
                for action in case["tool_calling"]:
                    tool, a = action["tool"], action["args"]
                    p = a.get("pizza")
                    if tool == "place":
                        if a["item"] == "dough":
                            self.assertEqual(k.call("create", {"dough": a["kind"]})["id"], p)
                        elif a["item"] in {"sauce", "cheese"}:
                            paint(k, p, a["item"], kind=a.get("kind"), region=a["region"])
                        else:
                            points = [(x, y) for x, y in GUIDE_POINTS
                                      if a["region"] == "whole" or (x < 0) == (a["region"] == "left")]
                            count = a["count"]
                            if a["region"] == "whole":
                                # A physical whole-pizza placement spans both halves.
                                points = sorted(points, key=lambda pt: pt[0])
                                points = [points[0], points[-1], *points[1:-1]]
                                requirements = case["answer"].get("pizzas", [])[p-1]
                                if a["kind"] not in requirements.get("topping_counts", {}):
                                    count = max(2, count)
                            for i in range(count):
                                x, y = points[i % len(points)]
                                k.call("place_toppings", {"pizza": p, "kind": a["kind"], "points": [[x, y]]})
                    elif tool == "bake":
                        k.call(tool, a)
                    elif tool in {"cut", "serve"}:
                        if tool == "cut":
                            for i in range(a["slices"] // 2):
                                k.call("cut", {"pizza": p, "angle": 180 * i / (a["slices"] // 2)})
                        else:
                            k.call("serve", a)
                    else:
                        k.call(tool, a)
                self.assertTrue(session.finish()["passed"])


if __name__ == "__main__":
    unittest.main()
