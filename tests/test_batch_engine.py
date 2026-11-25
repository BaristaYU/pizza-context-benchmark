import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pizzabench import providers
from pizzabench.ai_runner import reference_plan_for
from pizzabench.batch_engine import run_batch
from pizzabench.comparison import compare_summaries
from pizzabench.controls import build_controls, source_digest
from pizzabench.game_cli import ToolEnvironment
from pizzabench.game_orders import load_orders
from pizzabench.providers import MistralSession, ProviderError


SECRET = "sk-batch-secret"
CASES = [order for order in load_orders(None) if order["id"] in {"en100_001", "en100_002"}]


def plan(case):
    return reference_plan_for(case, ToolEnvironment(case).session.kitchen.snapshot()) + [{"tool": "finish", "args": {}}]


class Scripted:
    """A provider session that plays the reference plan, several calls per turn."""

    def __init__(self, provider, model, per_turn=4, cost_tokens=1000, fail=None):
        self.provider, self.model = provider, model
        self.settings = {"provider": provider.title(), "api": provider + "-api", "max_tokens": 8192}
        self.per_turn, self.cost_tokens, self.fail = per_turn, cost_tokens, fail
        self.queue = None

    def ask(self, prompt, tools):
        if self.fail:
            raise ProviderError(self.fail, "rejected " + SECRET)
        if self.queue is None:
            case = next(case for case in CASES if case["question"]["order_text"] in prompt)
            self.queue = plan(case)
        actions, self.queue = self.queue[:self.per_turn], self.queue[self.per_turn:]
        return actions, {"input": self.cost_tokens, "output": 10, "total": self.cost_tokens + 10}

    def reply(self, results, idle=None):
        pass

    def close(self):
        pass


def factory(**options):
    def build(provider, key, model, **_):
        return Scripted(provider, model, **options)
    return build


class BatchTest(unittest.TestCase):
    def run_batch(self, folder, provider="anthropic", model="claude-haiku-5-5", **options):
        session_options = {key: options.pop(key) for key in ("per_turn", "cost_tokens", "fail") if key in options}
        return run_batch(CASES, provider, model, SECRET, folder, request_interval=0,
                         session_factory=factory(**session_options), **options)

    def test_run_writes_reports_history_and_redacts_key(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "run"
            result = self.run_batch(folder)
            summary = result["summary"]
            self.assertEqual((summary["attempted"], summary["passed"]), (2, 2))
            self.assertGreater(summary["cumulative_cost_usd"], 0)
            for name in ("summary.json", "report.html", "run_manifest.json", "en100_001.json"):
                self.assertTrue((folder / name).exists(), name)
            self.assertTrue((folder / "history" / "en100_001" / "attempt_0001.json").exists())
            self.assertNotIn("제작 품질", (folder / "report.html").read_text(encoding="utf-8"))
            for path in folder.rglob("*.json"):
                self.assertNotIn(SECRET, path.read_text(encoding="utf-8"))

    def test_resume_keeps_finished_cases_and_retries_api_errors(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "run"
            first = self.run_batch(folder, fail=500)
            self.assertEqual(first["summary"]["api_errors"], 2)
            self.assertNotIn(SECRET, json.dumps(first["summary"], ensure_ascii=False))
            second = self.run_batch(folder, resume=True)
            self.assertEqual(second["summary"]["passed"], 2)
            report = json.loads((folder / "en100_001.json").read_text(encoding="utf-8"))
            self.assertEqual([attempt["termination"] for attempt in report["attempts"]], ["api_error", "finished"])
            third = self.run_batch(folder, resume=True, fail=500)  # finished cases are not called again
            self.assertEqual(third["summary"]["passed"], 2)

    def test_resume_rejects_changed_service_settings(self):
        def changed(provider, key, model, **_):
            session = Scripted(provider, model)
            session.settings = {**session.settings, "max_tokens": 1024}
            return session
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "run"
            self.run_batch(folder, fail=500)
            with self.assertRaisesRegex(ValueError, "서비스 생성 설정"):
                run_batch(CASES, "anthropic", "claude-haiku-5-5", SECRET, folder, resume=True,
                          request_interval=0, session_factory=changed)
            # The unchanged settings still resume.
            self.assertEqual(self.run_batch(folder, resume=True)["summary"]["passed"], 2)

    def test_resume_rejects_changed_experiment(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "run"
            self.run_batch(folder, fail=500)
            with self.assertRaisesRegex(ValueError, "통제변수"):
                self.run_batch(folder, resume=True, max_requests=10)

    def test_total_budget_stops_the_batch(self):
        with tempfile.TemporaryDirectory() as root:
            # 1M input tokens per request costs $0.10 on Haiku; the first case spends past $0.15.
            result = self.run_batch(Path(root) / "run", cost_tokens=1_000_000, max_total_cost_usd=0.15, per_turn=2)
            summary = result["summary"]
            self.assertEqual(summary["batch_stop_reason"], "cost_limit")
            self.assertEqual(summary["not_run"], 1)
            self.assertEqual(summary["rows"][0]["termination"], "cost_limit")

    def test_unopenable_case_fails_before_any_request(self):
        broken = [{**CASES[0], "state": {"environment_version": "mock-kitchen-2"}}]
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(ValueError, "주방에서 열 수 없는"):
            run_batch(broken, "anthropic", "claude-haiku-5-5", SECRET, Path(root) / "run",
                      request_interval=0, session_factory=factory())


class ControlsTest(unittest.TestCase):
    def test_experiment_fingerprint_is_shared_across_services(self):
        gemini = build_controls(CASES, {"provider": "Gemini", "api": "generateContent"})
        openai = build_controls(CASES, {"provider": "OpenAI", "api": "chat/completions"})
        self.assertEqual(gemini["fingerprint"], openai["fingerprint"])
        self.assertNotEqual(gemini["service_fingerprint"], openai["service_fingerprint"])
        self.assertNotEqual(build_controls(CASES, {}, max_requests=10)["fingerprint"], gemini["fingerprint"])
        self.assertNotEqual(build_controls(CASES, {}, rules="rules")["fingerprint"], gemini["fingerprint"])

    def test_source_digest_ignores_bom_and_line_endings(self):
        with tempfile.TemporaryDirectory() as root:
            unix, windows = Path(root) / "a.py", Path(root) / "b.py"
            unix.write_bytes(b"x = 1\ny = 2\n")
            windows.write_bytes(b"\xef\xbb\xbfx = 1\r\ny = 2\r\n")
            self.assertEqual(source_digest(unix), source_digest(windows))


class ComparisonTest(unittest.TestCase):
    def test_services_compare_when_experiment_matches_and_settings_are_reported(self):
        summaries = []
        with tempfile.TemporaryDirectory() as root:
            for provider, model in (("anthropic", "claude-haiku-5-5"), ("gemini", "gemini-3.1-flash-lite")):
                summaries.append(BatchTest.run_batch(BatchTest(), Path(root) / provider, provider, model)["summary"])
        comparison = compare_summaries(summaries)
        self.assertTrue(comparison["comparable"])
        self.assertTrue(any("생성 설정" in warning for warning in comparison["warnings"]))
        self.assertIsNotNone(comparison["runs"][0]["cumulative_cost_usd"])


class CompatibleProviderTest(unittest.TestCase):
    def test_mistral_uses_its_endpoint(self):
        calls = []

        def fake(url, headers, body=None, **_):
            calls.append((url, body))
            return {"choices": [{"message": {"content": "", "tool_calls": []}}], "usage": {}}
        with mock.patch.object(providers, "request_json", side_effect=fake):
            MistralSession(SECRET, "mistral-small-latest").ask("prompt", [])
        self.assertTrue(calls[0][0].startswith("https://api.mistral.ai/v1/"))
        self.assertTrue(calls[0][1]["parallel_tool_calls"])


if __name__ == "__main__":
    unittest.main()
