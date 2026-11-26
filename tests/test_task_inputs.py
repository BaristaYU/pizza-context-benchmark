from copy import deepcopy
import json
from pathlib import Path
import unittest

from pizzabench.task_inputs import build_task_input
from pizzabench.data_io import read_jsonl as load_jsonl


ROOT = Path(__file__).resolve().parent.parent
CASE = next(row for row in load_jsonl(ROOT / "data/samples/benchmark_cases_fixed_recipes.jsonl")
            if row["id"] == "s_en_fixed_000439")


class TaskInputTests(unittest.TestCase):
    def test_order_tasks_do_not_receive_reference_answers(self):
        row = deepcopy(CASE)
        row["question"]["recipe_text"] = "HIDDEN_RECIPE"
        row["question"]["clarification_text"] = "HIDDEN_CLARIFICATION"
        row["linguistics"]["initial"] = {"secret": "HIDDEN_ANALYSIS"}
        row["answer"] = {"secret": "HIDDEN_ANSWER"}
        row["tool_calling"] = [{"secret": "HIDDEN_PLAN"}]
        row["execution"] = {"secret": "HIDDEN_EXECUTION"}
        row["future_reference_field"] = "HIDDEN_NEW_FIELD"
        for task in ("NLU", "E2E"):
            with self.subTest(task=task):
                inputs = build_task_input(row, task)
                self.assertEqual(inputs["question"], {"order_text": CASE["question"]["order_text"]})
                self.assertNotIn("HIDDEN_", json.dumps(inputs))

    def test_clarification_is_revealed_only_when_requested(self):
        for task in ("NLU", "E2E"):
            with self.subTest(task=task):
                initial = build_task_input(CASE, task)
                clarified = build_task_input(CASE, task, clarified=True)
                self.assertNotIn("clarification_text", initial["question"])
                self.assertEqual(clarified["question"]["clarification_text"], CASE["question"]["clarification_text"])
                self.assertNotIn("recipe_text", clarified["question"])

    def test_reasoning_receives_only_the_visible_reference_analysis(self):
        initial = build_task_input(CASE, "Reasoning")
        clarified = build_task_input(CASE, "Reasoning", clarified=True)
        self.assertEqual(set(initial), {"linguistics", "menu"})
        self.assertEqual(set(clarified), set(initial))
        self.assertEqual(initial["linguistics"], CASE["linguistics"]["initial"])
        self.assertEqual(clarified["linguistics"], CASE["linguistics"]["clarified"])

    def test_planning_and_execution_receive_their_declared_inputs(self):
        planning = build_task_input(CASE, "Planning")
        self.assertEqual(set(planning), {"answer", "state"})
        self.assertEqual(planning["answer"], CASE["answer"])
        for task in ("Tool Use", "Computer Use"):
            with self.subTest(task=task):
                inputs = build_task_input(CASE, task)
                self.assertEqual(set(inputs), {"tool_calling", "state"})
                self.assertEqual(inputs["tool_calling"], CASE["tool_calling"])

    def test_unknown_task_and_missing_clarification_fail(self):
        with self.assertRaises(ValueError):
            build_task_input(CASE, "unknown")
        with self.assertRaises(ValueError):
            build_task_input(CASE, "Planning", clarified=True)
        with self.assertRaises(ValueError):
            build_task_input(CASE, "E2E", clarified="false")
        row = deepcopy(CASE)
        row["question"]["clarification_text"] = None
        with self.assertRaises(ValueError):
            build_task_input(row, "E2E", clarified=True)
        row = deepcopy(CASE)
        row["linguistics"].pop("clarified")
        with self.assertRaises(ValueError):
            build_task_input(row, "Reasoning", clarified=True)

    def test_model_input_cannot_mutate_reference_data(self):
        row = deepcopy(CASE)
        inputs = build_task_input(row, "Planning")
        inputs["state"]["inventory"]["topping"]["fig"] = 0
        inputs["answer"]["pizzas"][0]["cuts"] = 99
        self.assertEqual(row, CASE)


if __name__ == "__main__":
    unittest.main()
