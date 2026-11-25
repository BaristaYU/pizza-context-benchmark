from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pizzabench.data_io import read_jsonl as load_jsonl
from pizzabench.environment import PizzaEnvironment, ToolError, replay
from pizzabench.grading import evaluate


def run_plan(plan, requirements, initial_state=None):
    """Play T in the reference environment and grade the final state against A."""
    environment = PizzaEnvironment(initial_state=initial_state)
    starting_state = environment.snapshot()
    failure = None
    if not isinstance(plan, list):
        failure = "T must be an array"
    else:
        for index, action in enumerate(plan):
            try:
                if not isinstance(action, dict) or set(action) != {"tool", "args"}:
                    raise ToolError(f"T[{index}] must contain tool and args")
                environment.call(action["tool"], action["args"])
            except ToolError as exc:
                failure = str(exc)
                break
    result = evaluate(requirements, environment.snapshot())
    if failure:
        result["passed"] = False
        result["errors"].insert(0, failure)
    return {"environment_version": environment.version, "state": starting_state, "tool_calling": plan,
            "execution": environment.execution(), "score": result}


ROOT = Path(__file__).resolve().parent.parent
SAMPLES = load_jsonl(ROOT / "data/samples/benchmark_cases_fixed_recipes.jsonl")
BY_ID = {row["id"]: row for row in SAMPLES}
REFERENCES = {row["id"]: row["execution"] for row in SAMPLES}


def sample(number):
    return deepcopy(BY_ID[f"s_en_fixed_{number:06d}"])


def reference(number):
    return deepcopy(REFERENCES[f"s_en_fixed_{number:06d}"])


class ExecutionTests(unittest.TestCase):
    def test_all_reference_results_are_observed_and_satisfy_a(self):
        self.assertEqual(len(SAMPLES), 10)
        for row in SAMPLES:
            with self.subTest(id=row["id"]):
                actual = replay(row["tool_calling"], initial_state=row["state"]).execution()
                self.assertEqual(REFERENCES[row["id"]], actual)
                self.assertTrue(evaluate(row["answer"], actual)["passed"])

    def test_source_fields_and_stable_links(self):
        sources = load_jsonl(ROOT / "data/samples/question_fixed_recipes.jsonl")
        source_index = {row["id"]: row for row in sources}
        for row in sources:
            self.assertEqual(set(row), {"id", "difficulty", "language", "order_text", "clarification_text", "recipe_text"})
        for row in SAMPLES:
            self.assertEqual(set(row), {"id", "environment_version", "question", "state", "linguistics", "answer", "tool_calling", "execution"})
            self.assertEqual(row["question"], source_index[row["question"]["id"]])
            self.assertEqual(row["environment_version"], PizzaEnvironment.version)
            self.assertEqual(set(row["linguistics"]), {"initial", "clarified"})

    def test_json_template_is_a_real_sample(self):
        row = sample(439)
        expected = {"benchmark_case": row, "question": row["question"], "execution": row["execution"]}
        expected.update({name.lower(): row[name] for name in ("state", "linguistics", "answer", "tool_calling")})
        for name, value in expected.items():
            with self.subTest(template=name):
                directory = ROOT / "schemas" if name == "benchmark_case" else ROOT / "schemas/Q-SLATE"
                actual = json.loads((directory / f"{name}_schema.json").read_text(encoding="utf-8"))
                self.assertEqual(actual, value)

    def test_ingredients_require_spread_dough_and_failure_is_atomic(self):
        env = PizzaEnvironment()
        env.call("place", {"pizza": 1, "item": "dough", "kind": "regular"})
        before = env.snapshot()
        with self.assertRaises(ToolError):
            env.call("place", {"pizza": 1, "item": "sauce", "kind": "tomato", "region": "whole"})
        self.assertEqual(env.snapshot(), before)
        self.assertFalse(env.trace[-1]["ok"])

    def test_cutting_before_baking_fails(self):
        env = replay(sample(1)["tool_calling"][:2])
        with self.assertRaises(ToolError):
            env.call("cut", {"pizza": 1, "slices": 6})

    def test_sauce_cannot_be_added_after_cheese(self):
        env = replay(sample(439)["tool_calling"][:4])
        with self.assertRaises(ToolError):
            env.call("place", {"pizza": 1, "item": "sauce", "kind": "pesto", "region": "whole"})

    def test_baking_cannot_follow_cutting(self):
        env = replay(sample(1)["tool_calling"][:-1])
        with self.assertRaises(ToolError):
            env.call("bake", {"pizza": 1})

    def test_submitted_pizza_is_immutable(self):
        env = replay(sample(1)["tool_calling"])
        for action in ("spread", "bake", "serve"):
            with self.subTest(action=action), self.assertRaises(ToolError):
                env.call(action, {"pizza": 1})

    def test_any_is_not_an_executable_sauce(self):
        env = replay(sample(1)["tool_calling"][:2])
        with self.assertRaises(ToolError):
            env.call("place", {"pizza": 1, "item": "sauce", "kind": "any", "region": "whole"})

    def test_invalid_counts_and_unknown_materials_fail(self):
        env = replay(sample(1)["tool_calling"][:2])
        for count in (0, -1, True, 1.5):
            with self.subTest(count=count), self.assertRaises(ToolError):
                env.call("place", {"pizza": 1, "item": "topping", "kind": "olive", "count": count, "region": "whole"})
        with self.assertRaises(ToolError):
            env.call("place", {"pizza": 1, "item": "topping", "kind": "imaginary", "count": 1, "region": "whole"})

    def test_argument_errors_do_not_become_python_type_errors(self):
        env = PizzaEnvironment()
        for tool, args in [("unknown", {}), ("place", []), ("place", {}),
                           ("place", {"pizza": True, "item": "dough", "kind": "regular"}),
                           ("observe", {"extra": True})]:
            with self.subTest(tool=tool, args=args), self.assertRaises(ToolError):
                env.call(tool, args)

    def test_a_omissions_allow_different_sauce_baking_and_slices(self):
        row = sample(202)
        for action in row["tool_calling"]:
            if action["tool"] == "place" and action["args"]["item"] == "sauce":
                action["args"]["kind"] = "pesto"
            elif action["tool"] == "cut":
                action["args"]["slices"] = 8
        bake_index = next(index for index, action in enumerate(row["tool_calling"]) if action["tool"] == "bake")
        row["tool_calling"].insert(bake_index, {"tool": "bake", "args": {"pizza": 1}})
        self.assertTrue(run_plan(row["tool_calling"], row["answer"])["score"]["passed"])

    def test_extra_topping_fails_even_if_requested_topping_is_present(self):
        row = sample(202)
        index = next(index for index, action in enumerate(row["tool_calling"]) if action["tool"] == "bake")
        row["tool_calling"].insert(index, {"tool": "place", "args": {"pizza": 1, "item": "topping", "kind": "olive", "count": 1, "region": "whole"}})
        self.assertFalse(run_plan(row["tool_calling"], row["answer"])["score"]["passed"])

    def test_half_swap_must_be_consistent_across_all_ingredients(self):
        row = sample(13)
        for action in row["tool_calling"]:
            args = action["args"]
            if args.get("region") in ("left", "right"):
                args["region"] = "right" if args["region"] == "left" else "left"
        self.assertTrue(run_plan(row["tool_calling"], row["answer"])["score"]["passed"])
        next(action for action in row["tool_calling"] if action["args"].get("kind") == "onion")["args"]["region"] = "right"
        self.assertFalse(run_plan(row["tool_calling"], row["answer"])["score"]["passed"])

    def test_explicit_direction_is_strict(self):
        row = sample(13)
        row["answer"]["pizzas"][0].pop("allow_half_swap")
        for action in row["tool_calling"]:
            args = action["args"]
            if args.get("region") in ("left", "right"):
                args["region"] = "right" if args["region"] == "left" else "left"
        self.assertFalse(run_plan(row["tool_calling"], row["answer"])["score"]["passed"])

    def test_pizza_matching_is_unordered_and_not_greedy(self):
        execution = reference(123)["final_state"]
        execution["pizzas"][1]["cuts"] = 6
        a = {"pizza_count": 2, "pizzas": [{"cheese": True}, {"cuts": 8}]}
        self.assertTrue(evaluate(a, execution)["passed"])
        a["pizzas"] = [{"cuts": 8}, {"cuts": 8}]
        self.assertFalse(evaluate(a, execution)["passed"])

    def test_alternatives_cannot_be_mixed(self):
        execution = reference(1)["final_state"]
        a = {"alternatives": [
            {"pizzas": [{"cheese": False, "cuts": 8}]},
            {"pizzas": [{"cheese": True, "cuts": 6}]},
        ]}
        self.assertFalse(evaluate(a, execution)["passed"])
        a["alternatives"].append({"pizzas": [{"cheese": False, "cuts": 6}]})
        self.assertTrue(evaluate(a, execution)["passed"])

    def test_side_counts_and_total_ranges(self):
        row = sample(202)
        onion = next(action for action in row["tool_calling"] if action["args"].get("kind") == "onion")
        index = row["tool_calling"].index(onion)
        row["tool_calling"][index:index+1] = [
            {"tool": "place", "args": {"pizza": 1, "item": "topping", "kind": "onion", "count": 2, "region": "left"}},
            {"tool": "place", "args": {"pizza": 1, "item": "topping", "kind": "onion", "count": 3, "region": "right"}},
        ]
        execution = replay(row["tool_calling"]).snapshot()
        self.assertEqual(execution["pizzas"][0]["topping_counts"]["onion"], {"left": 2, "right": 3})
        self.assertTrue(evaluate({"pizzas": [{"topping_counts": {"onion": {"left": 2, "right": 3}}}]}, execution)["passed"])
        self.assertTrue(evaluate({"pizzas": [{"topping_counts": {"onion": {"min": 3, "max": 6}}, "topping_count": 5}]}, execution)["passed"])
        self.assertFalse(evaluate({"pizzas": [{"topping_counts": {"onion": 4}}]}, execution)["passed"])

    def test_partial_submission_and_infeasible_plans_fail(self):
        row = sample(123)
        result = run_plan(row["tool_calling"][:-1], row["answer"])
        self.assertFalse(result["execution"]["final_state"]["submitted"])
        self.assertFalse(result["score"]["passed"])
        result = run_plan([{"tool": "cut", "args": {"pizza": 1, "slices": 6}}], {})
        self.assertFalse(result["score"]["passed"])
        self.assertFalse(result["execution"]["trace"][0]["ok"])

    def test_unsupported_conditions_are_not_silently_accepted(self):
        self.assertFalse(evaluate({"pizzas": [{"pattern": "animal"}]}, reference(1))["passed"])

    def test_large_quantity_is_not_a_new_scoring_limit(self):
        row = sample(202)
        next(action for action in row["tool_calling"] if action["args"].get("kind") == "onion")["args"]["count"] = 100_000
        row["state"]["inventory"]["topping"]["onion"] = 100_000
        result = run_plan(row["tool_calling"], row["answer"], row["state"])
        self.assertTrue(result["score"]["passed"])
        self.assertEqual(result["execution"]["final_state"]["pizzas"][0]["topping_counts"]["onion"], 100_000)

    def test_stock_consumption_and_failed_call_are_observable(self):
        row = sample(439)
        env = replay(row["tool_calling"][:5], initial_state=row["state"])
        state = env.snapshot()
        self.assertEqual(state["inventory"]["topping"]["sausage"], 82)
        self.assertEqual(state["inventory"]["dough"]["regular"], 99)
        self.assertEqual(state["inventory"]["sauce"]["tomato"], 99)
        with self.assertRaises(ToolError):
            env.call("place", {"pizza": 1, "item": "topping", "kind": "fig", "region": "left", "count": 101})
        self.assertEqual(env.snapshot(), state)
        env.call("place", {"pizza": 1, "item": "topping", "kind": "fig", "region": "left", "count": 9})
        self.assertEqual(env.snapshot()["inventory"]["topping"]["fig"], 91)
        self.assertFalse(env.execution()["trace"][-2]["ok"])

    def test_half_portions_consume_half_sauce_and_cheese(self):
        row = sample(13)
        result = run_plan(row["tool_calling"], row["answer"], row["state"])
        stock = result["execution"]["final_state"]["inventory"]
        self.assertEqual(stock["sauce"]["tomato"], 99.5)
        self.assertEqual(stock["cheese"], 99.5)

    def test_every_intermediate_state_can_resume_the_same_plan(self):
        for row in SAMPLES:
            env = PizzaEnvironment(initial_state=row["state"])
            for index, action in enumerate(row["tool_calling"]):
                with self.subTest(case=row["id"], step=index):
                    restored = PizzaEnvironment(initial_state=env.snapshot())
                    self.assertEqual(restored.snapshot(), env.snapshot())
                    actual = replay(row["tool_calling"][index:], initial_state=env.snapshot()).snapshot()
                    self.assertEqual(actual, REFERENCES[row["id"]]["final_state"])
                env.call(action["tool"], action["args"])

    def test_s_is_environment_state_and_replay_does_not_mutate_it(self):
        row = sample(439)
        before = deepcopy(row["state"])
        run_plan(row["tool_calling"], row["answer"], row["state"])
        self.assertEqual(row["state"], before)
        self.assertEqual(set(row["state"]), {"inventory", "pizza_count", "pizzas", "submitted"})

    def test_initial_stock_is_a_plan_feasibility_constraint(self):
        row = sample(439)
        row["state"]["inventory"]["topping"]["fig"] = 8
        result = run_plan(row["tool_calling"], row["answer"], row["state"])
        self.assertFalse(result["score"]["passed"])
        self.assertIn("Insufficient", result["score"]["errors"][0])

    def test_invalid_initial_stock_and_submission_fail(self):
        for quantity in (-1, True, 0.5):
            row = sample(1)
            row["state"]["inventory"]["dough"]["regular"] = quantity
            with self.subTest(quantity=quantity), self.assertRaises(ToolError):
                PizzaEnvironment(initial_state=row["state"])
        row = sample(1)
        row["state"]["submitted"] = True
        with self.assertRaises(ToolError):
            PizzaEnvironment(initial_state=row["state"])


if __name__ == "__main__":
    unittest.main()
