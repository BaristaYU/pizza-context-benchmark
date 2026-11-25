from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from pizzabench import english100_selection as selection, wiki_orders
from pizzabench.data_io import read_json, read_jsonl
from pizzabench.english100 import complete_case, make_initial_state, rebuild
from pizzabench.game import GameSession
from pizzabench.game_orders import load_orders
from pizzabench.l_to_a import answer_from_form, same_answer
from pizzabench.linguistics_form import validate
from pizzabench.task_inputs import build_task_input


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/english100"


class English100Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = read_jsonl(DATA / "benchmark_cases.jsonl")

    def test_rebuild_reproduces_every_stored_file(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "english100"
            shutil.copytree(DATA, target)
            rebuild(target)
            for path in sorted(DATA.rglob("*.json*")):
                with self.subTest(file=path.name):
                    self.assertEqual(path.read_bytes(), (target / path.relative_to(DATA)).read_bytes())

    def test_cases_hold_only_benchmark_fields(self):
        self.assertEqual([c["id"] for c in self.cases], [f"en100_{n:03d}" for n in range(1, 101)])
        for case in self.cases:
            self.assertEqual(set(case), {"id", "environment_version", "question", "source", "state", "linguistics",
                                         "answer", "review", "tool_calling", "execution", "reference_evaluation"})
            self.assertEqual(set(case["question"]), {"language", "order_text", "clarification_text", "difficulty"})
            self.assertTrue(case["reference_evaluation"]["passed"])

    def test_question_and_answer_come_from_the_wiki(self):
        data = wiki_orders.load()
        for case in self.cases:
            with self.subTest(case=case["id"]):
                source = case["source"]
                entry_index, order_index = map(int, source["wiki_key"].split(":"))
                entry = data["entries"][entry_index]
                order = entry["orders"][order_index]
                self.assertEqual(case["question"]["order_text"], wiki_orders.plain_text(order["order"]))
                self.assertEqual(case["question"]["clarification_text"], wiki_orders.plain_text(order["clarification"]))
                self.assertEqual(source["recipe"], entry["recipe"])
                count = len(wiki_orders.pizzas(entry["recipe"]))
                expected = wiki_orders.answer(entry["recipe"], cuts=[source["cuts"]] * count, bake=[source["bake"]] * count)
                self.assertEqual(case["answer"], expected)

    def test_clarified_l_leads_to_a_through_the_menu(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                for stage in ("initial", "clarified"):
                    validate(case["linguistics"][stage])
                self.assertTrue(same_answer(answer_from_form(case["linguistics"]["clarified"]), case["answer"]))

    def test_selection_is_balanced_and_keeps_reserves(self):
        tiers = Counter(c["question"]["difficulty"]["ocs"] for c in self.cases)
        self.assertEqual(tiers, selection.QUOTAS)
        self.assertEqual(Counter(c["question"]["difficulty"]["ocs"] for c in self.cases[:50]), {"하": 17, "중": 17, "상": 16})
        record = read_json(DATA / "selection.json")
        self.assertEqual([s["wiki_key"] for s in record["selected"]], [c["source"]["wiki_key"] for c in self.cases])
        used = {c["source"]["wiki_key"] for c in self.cases}
        for tier, reserve in record["reserves"].items():
            self.assertTrue(reserve)
            self.assertFalse(used & {r["wiki_key"] for r in reserve})
            self.assertEqual({r["ocs"] for r in reserve}, {tier})
        self.assertEqual({c["question"]["difficulty"]["lcs"]["initial"] for c in self.cases}, {None})

    def test_dropping_a_case_keeps_the_other_numbers(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import select_english100
        target_case = self.cases[4]
        with TemporaryDirectory() as directory:
            target = Path(directory) / "english100"
            shutil.copytree(DATA, target)
            # The replacement has no L draft yet, so the script stops before rebuilding.
            code = select_english100.main(["--output", str(target), "--drop", target_case["source"]["wiki_key"],
                                           "--reason", "test"])
            after = read_jsonl(target / "benchmark_cases.jsonl")
            dropped = read_json(target / "selection.json")["dropped"]
        self.assertEqual(code, 1)
        self.assertEqual(dropped, {target_case["source"]["wiki_key"]: "test"})
        changed = [(a["id"], b["id"]) for a, b in zip(self.cases, after) if a["source"]["wiki_key"] != b["source"]["wiki_key"]]
        self.assertEqual(changed, [(target_case["id"], target_case["id"])])
        self.assertEqual(after[4]["question"]["difficulty"]["ocs"], target_case["question"]["difficulty"]["ocs"])

    def test_half_pizza_alternatives_each_execute(self):
        answer = wiki_orders.answer("Cheese + (Tomato Sauce + Pepperoni) + (Sauce + Olive)")
        self.assertEqual(len(answer["alternatives"]), 2)
        for option in answer["alternatives"]:
            case = {"id": "half_test", "question": {"order_text": "test"}, "state": make_initial_state(), "answer": option}
            self.assertTrue(complete_case(case)["reference_evaluation"]["outcome"]["passed"])

    def test_case_state_restored_by_session_and_loader(self):
        orders = {c["id"]: c for c in load_orders(DATA / "benchmark_cases.jsonl")}
        case = deepcopy(self.cases[0])
        case["state"]["inventory"]["topping"]["pumpkin"] = 7
        case["state"]["config"]["oven_seconds"] = 2.5
        session = GameSession(case, oven_seconds=9)
        self.assertEqual(session.initial_state, case["state"])
        session.call("create", {"dough": "wheat"})
        session.reset()
        self.assertEqual(session.observe()["state"], case["state"])
        self.assertEqual(orders[self.cases[0]["id"]]["state"], self.cases[0]["state"])

    def test_task_inputs_are_the_stored_files(self):
        stored = read_jsonl(DATA / "inputs/reasoning_clarified.jsonl")
        self.assertEqual(stored[0]["model_input"], build_task_input(self.cases[0], "Reasoning", clarified=True))
        self.assertIn("menu", stored[0]["model_input"])
        recipes = {c["id"]: c["source"]["recipe"] for c in self.cases}
        for name in ("e2e", "nlu_initial", "nlu_clarified", "reasoning_clarified", "planning", "tool_use"):
            for row in read_jsonl(DATA / f"inputs/{name}.jsonl"):
                self.assertNotIn("source", row["model_input"])
                self.assertNotIn(recipes[row["case_id"]], json.dumps(row["model_input"]))


if __name__ == "__main__":
    unittest.main()
