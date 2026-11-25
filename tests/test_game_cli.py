from copy import deepcopy
import io
import json
from queue import Queue
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from pizzabench.game import GameSession
from pizzabench.game_cli import ToolEnvironment, read_json, serve, tool_definitions
from pizzabench.game_orders import load_orders
from pizzabench.kitchen import Kitchen


ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / "examples/mock_game_olive.json").read_text(encoding="utf-8"))


def execute(plan, reference=None, *, fail_first=False):
    session = GameSession(load_orders()[0], reference_plan=reference)
    if fail_first:
        try:
            session.call("cut", {"pizza": 1, "angle": 0})
        except ValueError:
            pass
    for action in plan:
        session.call(action["tool"], action["args"])
    session.finish()
    return session


class ExecutionScoringTests(unittest.TestCase):
    def test_outcome_and_plan_order_are_distinct(self):
        reordered = deepcopy(PLAN)
        reordered[2], reordered[3] = reordered[3], reordered[2]
        session = execute(reordered, PLAN)
        self.assertTrue(session.score["passed"])
        self.assertFalse(session.evaluation["plan"]["passed"])
        self.assertFalse(session.evaluation["passed"])
        self.assertTrue(execute(reordered).evaluation["passed"])

    def test_observations_and_failed_retry_are_allowed(self):
        plan = []
        for action in PLAN:
            plan.append({"tool": "observe", "args": {}})
            plan.append(action)
        session = execute(plan, PLAN, fail_first=True)
        self.assertTrue(session.evaluation["passed"])
        self.assertEqual(session.evaluation["metrics"]["failed_calls"], 1)
        self.assertEqual(session.evaluation["metrics"]["simulation_seconds"], 6)

    def test_wrong_ingredient_fails_outcome(self):
        plan = deepcopy(PLAN)
        for action in plan:
            if action["tool"] == "place_toppings":
                action["args"]["kind"] = "mushroom"
        result = execute(plan, PLAN).evaluation
        self.assertFalse(result["outcome"]["passed"])
        self.assertFalse(result["plan"]["passed"])
        self.assertTrue(result["outcome"]["errors"])


class ToolEnvironmentTests(unittest.TestCase):
    def test_ready_does_not_leak_answers_and_fixed_mode_exposes_only_plan_and_state(self):
        normal = ToolEnvironment(load_orders()[0]).ready()
        self.assertEqual(normal["task"], "order_execution")
        self.assertEqual(set(normal["observation"]), {"question", "state"})
        self.assertEqual(set(normal["observation"]["question"]), {"order_text"})
        self.assertNotIn('"answer"', json.dumps(normal))
        fixed = ToolEnvironment(load_orders()[0], reference_plan=PLAN)
        ready = fixed.ready()
        self.assertEqual(ready["task"], "tool_use")
        self.assertEqual(set(ready["observation"]), {"state"})
        self.assertEqual(ready["plan"], PLAN)
        self.assertNotIn("clarify", [r["name"] for r in ready["tools"]])
        self.assertFalse(fixed.request('{"tool":"clarify"}')["ok"])

    def test_invalid_protocol_and_tool_errors_do_not_end_the_session(self):
        env = ToolEnvironment(load_orders()[0])
        initial = env.session.kitchen.snapshot()
        for text in ['not json', '[]', '{"tool":"observe","tool":"finish"}',
                     '{"tool":"cut","args":{"pizza":1,"angle":NaN}}',
                     '{"tool":"cut","args":{"pizza":1,"angle":1e9999}}',
                     '{"tool":"wait","args":{"seconds":1}}',
                     '{"tool":"create","args":null}']:
            with self.subTest(text=text):
                reply = env.request(text)
                self.assertFalse(reply["ok"])
                self.assertFalse(reply["done"])
                self.assertEqual(env.session.kitchen.snapshot(), initial)
        failed = env.request('{"id":2,"tool":"bake","args":{"pizza":1}}')
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["id"], 2)
        self.assertFalse(env.session.kitchen.trace[-1]["ok"])
        self.assertTrue(env.request('{"id":"next","tool":"create","args":{"dough":"regular"}}')["ok"])
        json.dumps(env.report(), allow_nan=False)

    def test_clarification_is_revealed_once_and_early_finish_can_recover(self):
        env = ToolEnvironment(load_orders()[0])
        self.assertFalse(env.request('{"tool":"finish"}')["ok"])
        result = env.request('{"tool":"clarify"}')
        self.assertTrue(result["ok"])
        self.assertIn("clarification_text", result["result"])
        self.assertFalse(env.request('{"tool":"clarify"}')["ok"])

    def test_wrong_reference_is_rejected_before_a_run(self):
        with self.assertRaises(ValueError):
            ToolEnvironment(load_orders()[0], reference_plan=[])

    def test_tools_publish_argument_types_and_use_kitchen_names(self):
        tools = {t["name"]: t for t in tool_definitions(Kitchen())}
        self.assertEqual(set(tools), set(Kitchen.ACTIONS) | {"finish", "clarify"})
        points = tools["place_toppings"]["parameters"]["properties"]["points"]
        self.assertEqual(points["items"]["items"]["type"], "number")
        self.assertNotIn("wait", tools)
        self.assertNotIn("take_out", tools)
        self.assertNotIn("any", tools["paint"]["parameters"]["properties"]["kind"]["enum"])

    def test_stream_has_one_response_per_request_and_terminal_score(self):
        env = ToolEnvironment(load_orders()[0], reference_plan=PLAN)
        commands = [*PLAN, {"tool": "finish", "args": {}}]
        stdin = io.StringIO("\n".join(json.dumps(r) for r in commands) + "\n")
        stdout = io.StringIO()
        self.assertEqual(serve(env, stdin, stdout), 0)
        replies = [json.loads(s) for s in stdout.getvalue().splitlines()]
        self.assertEqual(len(replies), len(commands) + 1)
        self.assertEqual(replies[0]["event"], "ready")
        self.assertTrue(replies[-1]["done"])
        self.assertTrue(replies[-1]["result"]["outcome"]["passed"])
        self.assertTrue(replies[-1]["result"]["plan"]["passed"])
        self.assertNotIn("quality", replies[-1]["result"])
        self.assertEqual(env.report()["status"], "COMPLETE")

    def test_eof_is_incomplete_without_final_grading_feedback(self):
        env = ToolEnvironment(load_orders()[0])
        stdout = io.StringIO()
        self.assertEqual(serve(env, io.StringIO('{"tool":"observe"}\n'), stdout), 1)
        self.assertEqual(env.report()["status"], "INCOMPLETE")
        self.assertIsNone(env.report()["evaluation"])
        self.assertEqual(json.loads(stdout.getvalue().splitlines()[-1])["event"], "end")

    def test_actual_cli_process_and_saved_execution_report(self):
        commands = "\n".join(json.dumps(r) for r in [*PLAN, {"tool": "finish"}]) + "\n"
        with TemporaryDirectory() as directory:
            output = Path(directory) / "run.json"
            result = subprocess.run([sys.executable, "-m", "pizzabench.game_cli", "--reference-plan",
                                     str(ROOT / "examples/mock_game_olive.json"), "--output", str(output)],
                                    input=commands, capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            replies = [json.loads(s) for s in result.stdout.splitlines()]
            self.assertTrue(replies[-1]["result"]["passed"])
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["evaluation"]["passed"])
            self.assertEqual(len(report["interactions"]), len(PLAN) + 1)
            self.assertEqual(len(report["execution"]["final_state"]["pizzas"][0]["pieces"]), 16)
            denied = subprocess.run([sys.executable, "-m", "pizzabench.game_cli", "--output", str(output)],
                                    input="", capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=10)
            self.assertEqual(denied.returncode, 2)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)

    def test_live_process_responds_before_stdin_is_closed(self):
        process = subprocess.Popen([sys.executable, "-m", "pizzabench.game_cli"], cwd=ROOT,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", bufsize=1)
        messages = Queue()
        def read_responses():
            for line in process.stdout:
                messages.put(json.loads(line))
        reader = Thread(target=read_responses, daemon=True)
        reader.start()
        try:
            self.assertEqual(messages.get(timeout=5)["event"], "ready")
            process.stdin.write('{"id":1,"tool":"create","args":{"dough":"regular"}}\n')
            process.stdin.flush()
            self.assertEqual(messages.get(timeout=5)["result"]["id"], 1)
            process.stdin.write('{"id":2,"tool":"cut","args":{"pizza":1,"angle":0}}\n')
            process.stdin.flush()
            self.assertFalse(messages.get(timeout=5)["ok"])
            process.stdin.write('{"id":3,"tool":"spread","args":{"pizza":1}}\n')
            process.stdin.flush()
            self.assertTrue(messages.get(timeout=5)["ok"])
            process.stdin.close()
            self.assertEqual(messages.get(timeout=5)["status"], "INCOMPLETE")
            self.assertEqual(process.wait(timeout=5), 1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if not process.stdin.closed:
                process.stdin.close()
            reader.join(timeout=5)
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
