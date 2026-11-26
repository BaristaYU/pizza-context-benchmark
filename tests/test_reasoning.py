from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pizzabench.data_io import read_json, write_jsonl
from pizzabench.l_to_a import answer_from_form
from pizzabench.linguistics_form import from_ticks
from pizzabench.reasoning import AnswerFormatError, SCORING_VERSION, parse_answer, score_response
from scripts import run_benchmark


class ReasoningScoringTests(unittest.TestCase):
    def test_malformed_answers_are_not_scored_as_content_errors(self):
        for text in ('not JSON', '{"pizza_count":true,"pizzas":[{}]}',
                     '{"pizza_count":1,"pizzas":[]}',
                     '{"alternatives":[{"pizza_count":2,"pizzas":[{}]}]}',
                     '{"pizza_count":1,"pizza_count":1,"pizzas":[{}]}',
                     '{"pizza_count":1,"pizzas":[{"cuts":NaN}]}',
                     '{"pizza_count":1,"pizzas":[{"sauce":"tomato"}]}'):
            with self.subTest(text=text):
                with self.assertRaises(AnswerFormatError):
                    parse_answer(text)

    def test_scoring_ignores_order_and_respects_direction(self):
        left = {"sauce": ["pesto", "tomato"], "sauce_placement": {"pesto": "left", "tomato": "right"},
                "toppings": ["olive", "fig"], "topping_counts": {"olive": {"left": 2, "right": 1}}}
        right = {"sauce": ["tomato", "pesto"], "sauce_placement": {"pesto": "right", "tomato": "left"},
                 "toppings": ["fig", "olive"], "topping_counts": {"olive": {"left": 1, "right": 2}}}
        expected = {"pizza_count": 2, "pizzas": [left, {}]}
        actual = {"pizza_count": 2, "pizzas": [{}, right]}
        _, score = score_response(expected, json.dumps(actual))
        self.assertEqual(score["status"], "condition_mismatch")
        self.assertIn("sauce_placement", score["differences"]["fields"])
        left["allow_half_swap"] = right["allow_half_swap"] = True
        _, score = score_response(expected, "```json\n" + json.dumps(actual) + "\n```")
        self.assertTrue(score["passed"])
        alternative = {"pizza_count": 1, "pizzas": [{"sauce": ["any"]}]}
        expected_choices = {"alternatives": [expected, alternative]}
        _, score = score_response(expected_choices, json.dumps({"alternatives": [alternative, actual]}))
        self.assertTrue(score["passed"])
        _, score = score_response(expected_choices, json.dumps(actual))
        self.assertEqual(score["differences"]["alternatives"]["missing"], [alternative])


class ReasoningCliTests(unittest.TestCase):
    def test_batch_sends_clarified_l_and_menu_and_persists_three_outcomes(self):
        form = from_ticks(": olive")
        expected = answer_from_form(form)
        cases = [{"id": name, "linguistics": {"initial": from_ticks(": fig"), "clarified": form},
                  "answer": expected, "question": {"order_text": "PRIVATE_QUESTION",
                  "clarification_text": "PRIVATE_CLARIFICATION"}, "source": {"recipe": "PRIVATE_RECIPE"},
                  "tool_calling": "PRIVATE_PLAN", "execution": "PRIVATE_EXECUTION"}
                 for name in ("pass", "bad_format", "wrong_condition")]
        wrong = deepcopy(expected)
        wrong["pizzas"][0]["sauce"] = ["tomato"]
        wrong["pizzas"][0]["sauce_placement"] = {"tomato": "whole"}
        answers = iter([json.dumps(expected), '{"pizza_count":2,"pizzas":[{}]}', json.dumps(wrong)])
        requests = []

        def request(_url, _headers, body, **_options):
            requests.append(deepcopy(body))
            return {"choices": [{"message": {"content": next(answers)}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}

        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            base = Path(directory)
            data = base / "cases.jsonl"
            output = base / "run"
            write_jsonl(data, cases)
            args = ["--task", "reasoning", "--provider", "vllm", "--model", "test-model",
                    "--data", str(data), "--request-interval", "0"]
            with patch.object(run_benchmark, "load_api_keys", return_value={"vllm": ""}), \
                    patch("pizzabench.providers.request_json", side_effect=request):
                self.assertEqual(run_benchmark.main([*args, "--output-dir", str(output)]), 0)
                self.assertEqual(run_benchmark.main([*args, "--resume", str(output)]), 0)
            self.assertEqual(len(requests), 3)
            for body in requests:
                self.assertNotIn("tools", body)
                self.assertEqual(len(body["messages"]), 1)
                prompt = body["messages"][0]["content"]
                self.assertNotIn("PRIVATE_", prompt)
                inputs = json.loads(prompt.rsplit("\n\n", 1)[-1])
                self.assertEqual(set(inputs), {"linguistics", "menu"})
                self.assertEqual(inputs["linguistics"], form)
            summary = read_json(output / "summary.json")
            self.assertEqual((summary["passed"], summary["attempted"], summary["valid_answers"]), (1, 3, 2))
            self.assertEqual((summary["format_errors"], summary["condition_mismatches"]), (1, 1))
            self.assertEqual(summary["scoring_version"], SCORING_VERSION)
            self.assertEqual(summary["controls"]["task"], "Reasoning")
            bad_format = read_json(output / "bad_format.json")
            self.assertIn("pizza_count", bad_format["score"]["errors"][0])
            self.assertIsNone(bad_format["normalized_answer"])
            wrong_condition = read_json(output / "wrong_condition.json")
            self.assertEqual(wrong_condition["response_text"], json.dumps(wrong))
            self.assertEqual(wrong_condition["normalized_answer"], wrong)
            self.assertEqual(wrong_condition["score"]["differences"]["fields"]["sauce"],
                             {"expected": ["any"], "actual": ["tomato"]})
