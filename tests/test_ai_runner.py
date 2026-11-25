import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pizzabench import ai_runner, providers
from pizzabench.ai_runner import cost_of, estimate_session, run_agent, summarise
from pizzabench.credentials import CredentialError, load_api_keys
from pizzabench.game_cli import main as cli_main
from pizzabench.game_orders import load_orders
from pizzabench.kitchen import REGION_CELLS, observable_state
from pizzabench.providers import AnthropicSession, GeminiSession, OpenAISession, ProviderError, gemini_schema


ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / "examples" / "mock_game_olive.json").read_text(encoding="utf-8"))
SECRET = "sk-test-secret-value"


def order(case_id="practice_olive"):
    return next(item for item in load_orders(None) if item["id"] == case_id)


class ScriptedSession:
    """Plays fixed actions one per turn, like a provider session would."""

    provider, model = "anthropic", "claude-haiku-5-5"
    settings = {"provider": "Scripted"}

    def __init__(self, actions):
        self.queue = list(actions)
        self.replies = []

    def ask(self, prompt, tools):
        self.prompt, self.tools = prompt, tools
        if not self.queue:
            return [], {"input": 10, "output": 1, "total": 11}
        return [self.queue.pop(0)], {"input": 1000, "output": 50, "total": 1050}

    def reply(self, results, idle=None):
        self.replies.append(results)

    def close(self):
        pass


class ObservableStateTest(unittest.TestCase):
    def test_s_reports_coverage_instead_of_internal_grids(self):
        pizza = {"id": 1, "topping_counts": {"olive": {"left": 2, "right": 0}},
                 "pieces": [{"kind": "olive", "x": -0.2, "y": 0}] * 2,
                 "coatings": {"tomato": list(REGION_CELLS["left"])},
                 "history": [{"key": "tomato"}]}
        state = observable_state({"ok": True, "result": pizza, "state": {"pizzas": [pizza]}})
        for value in (state["result"], state["state"]["pizzas"][0]):
            for internal in ("coatings", "history"):
                self.assertNotIn(internal, value)
            self.assertEqual(value["coverage"]["tomato"]["left"], 1.0)
            self.assertEqual(value["coverage"]["tomato"]["right"], 0.0)
            self.assertEqual(len(value["pieces"]), 2)


class RunAgentTest(unittest.TestCase):
    def test_reference_actions_finish_and_pass(self):
        session = ScriptedSession(PLAN + [{"tool": "finish", "args": {}}])
        result = run_agent(order(), session, max_requests=80)
        self.assertEqual(result["termination"], "finished")
        self.assertTrue(result["score"]["passed"])
        self.assertEqual(result["requests"], len(PLAN) + 1)
        # The model sees S; the execution record keeps the internal state used for grading.
        topping_reply = json.dumps(session.replies[4])
        self.assertIn("coverage", topping_reply)
        self.assertNotIn("coatings", topping_reply)
        # An action answers with the changed pizza; topping coordinates come from observe.
        self.assertNotIn("pieces", topping_reply)
        self.assertIn("coatings", json.dumps(result["execution"]["final_state"]))
        self.assertEqual(result["cost"]["input"], 1000 * (len(PLAN) + 1))
        self.assertTrue(result["cost"]["priced"])

    def test_prompt_hides_answer_and_reference(self):
        session = ScriptedSession([{"tool": "finish", "args": {}}])
        run_agent(order("en100_001"), session, max_requests=2)
        self.assertIn("order_text", session.prompt)
        for hidden in ('"answer"', "recipe_text", "quality", "tool_calling", "difficulty", "clarification_text"):
            self.assertNotIn(hidden, session.prompt)

    def test_prompt_is_only_the_ready_event(self):
        session = ScriptedSession([{"tool": "finish", "args": {}}])
        run_agent(order("en100_001"), session, max_requests=2)
        event = json.loads(session.prompt)
        self.assertEqual(set(event), {"event", "protocol", "task", "environment_version", "observation", "menu"})
        self.assertIn("Hawaiian", event["menu"]["recipes"])
        self.assertEqual(event["event"], "ready")

    def test_reply_without_tool_call_returns_observation(self):
        class Talker(ScriptedSession):
            def reply(self, results, idle=None):
                self.idle = idle
        session = Talker([])
        run_agent(order(), session, max_requests=2)
        self.assertEqual(json.loads(session.idle)["event"], "observation")

    def test_finish_before_boxing_is_a_tool_error_not_success(self):
        session = ScriptedSession([{"tool": "finish", "args": {}}] * 5)
        result = run_agent(order(), session, max_requests=10, max_consecutive_errors=5)
        self.assertEqual(result["termination"], "tool_error_limit")
        self.assertFalse(result["score"]["passed"] if result["score"] else False)

    def test_request_limit_marks_failure(self):
        session = ScriptedSession(PLAN[:3])
        result = run_agent(order(), session, max_requests=3)
        self.assertEqual(result["termination"], "request_limit")
        self.assertEqual(result["requests"], 3)

    def test_cost_limit_stops_before_next_request(self):
        class Expensive(ScriptedSession):
            def ask(self, prompt, tools):
                actions, _ = super().ask(prompt, tools)
                return actions, {"input": 1_000_000, "output": 0, "total": 1_000_000}  # $0.10 on Haiku
        result = run_agent(order(), Expensive(PLAN), max_requests=80, max_cost_usd=0.25)
        self.assertEqual(result["termination"], "cost_limit")
        self.assertEqual(result["requests"], 3)
        self.assertFalse(result["score"]["passed"] if result["score"] else False)

    def test_cost_limit_requires_a_price(self):
        class Unpriced(ScriptedSession):
            model = "unpriced-model"
        with self.assertRaises(ValueError):
            run_agent(order(), Unpriced([]), max_cost_usd=1)

    def test_provider_error_is_recorded_without_secret(self):
        class Failing(ScriptedSession):
            def ask(self, prompt, tools):
                raise ProviderError(429, "quota for " + SECRET)
        result = run_agent(order(), Failing([]), max_requests=3)
        self.assertEqual(result["termination"], "api_error")
        self.assertEqual(result["error_code"], 429)
        self.assertNotIn(SECRET, json.dumps(result, ensure_ascii=False))

    def test_summary_fields(self):
        result = run_agent(order(), ScriptedSession(PLAN + [{"tool": "finish", "args": {}}]), max_requests=80)
        summary = summarise(result)
        self.assertEqual(summary["passed"], True)
        self.assertEqual(summary["tool_calls"], len(PLAN) + 1)
        self.assertGreater(summary["cost_usd"], 0)


class EstimateTest(unittest.TestCase):
    class Offline:
        provider, model = "anthropic", "claude-haiku-5-5"

        def count_tokens(self, prompt, tools):
            raise ProviderError(None, "offline")

    def test_optimistic_is_below_conservative(self):
        report = estimate_session(order(), self.Offline(), max_requests=60)
        self.assertEqual(report["token_counting"], "fallback ratio")
        self.assertEqual(report["reference_plan_calls"], 10)
        self.assertLess(report["optimistic"]["total_usd"], report["conservative"]["total_usd"])
        self.assertEqual(report["conservative"]["turns"], 60)

    def test_s_keeps_each_turn_small(self):
        from pizzabench.ai_runner import conversation_profile, reference_plan_for
        from pizzabench.game_cli import ToolEnvironment
        case = order()
        plan = reference_plan_for(case, ToolEnvironment(case).session.kitchen.snapshot())
        self.assertLess(max(turn["response"] for turn in conversation_profile(case, plan)), 3000)

    def test_unpriced_model_reports_no_cost(self):
        self.assertFalse(cost_of([{"input": 1, "output": 1, "total": 2}], "openai", "unknown-model")["priced"])


class ProviderShapeTest(unittest.TestCase):
    """Request bodies and response parsing, with the network replaced by a recorder."""

    tools = [{"name": "place_topping", "description": "Place one topping.",
              "parameters": {"type": "object", "properties": {"pizza": {"type": "integer", "minimum": 1}},
                             "required": ["pizza"], "additionalProperties": False}},
             {"name": "finish", "description": "Finish.",
              "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}]

    def capture(self, response):
        calls = []

        def fake(url, headers, body=None, **_):
            calls.append({"url": url, "headers": headers, "body": json.loads(json.dumps(body))})
            return response
        return calls, mock.patch.object(providers, "request_json", side_effect=fake)

    def test_gemini_declarations_and_signature_round_trip(self):
        content = {"role": "model", "parts": [{"text": "Dough before toppings.", "thought": True},
                                              {"functionCall": {"name": "place_topping", "args": {"pizza": 1}},
                                               "thoughtSignature": "sig"}]}
        calls, patch = self.capture({"candidates": [{"content": content}],
                                     "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3,
                                                       "thoughtsTokenCount": 2, "totalTokenCount": 12}})
        session = GeminiSession(SECRET, "gemini-3.1-flash-lite")
        with patch:
            actions, usage = session.ask("prompt", self.tools)
            session.reply([{"ok": True}])
            session.ask("prompt", self.tools)
        declarations = calls[0]["body"]["tools"][0]["functionDeclarations"]
        self.assertEqual(declarations[0]["parameters"]["type"], "OBJECT")
        self.assertNotIn("additionalProperties", json.dumps(declarations))
        self.assertNotIn("parameters", declarations[1])
        self.assertEqual(actions, [{"tool": "place_topping", "args": {"pizza": 1}}])
        self.assertEqual(session.last_output["reasoning"], "Dough before toppings.")
        self.assertEqual(calls[0]["body"]["generationConfig"], {"thinkingConfig": {"includeThoughts": True}})
        self.assertEqual(usage["output"], 5)
        # The model content returns unchanged, signature included, before the function response.
        self.assertEqual(calls[1]["body"]["contents"][1], content)
        self.assertEqual(calls[1]["body"]["contents"][2]["parts"][0]["functionResponse"]["name"], "place_topping")
        self.assertNotIn(SECRET, json.dumps([c["body"] for c in calls]))

    def test_openai_responses_resend_encrypted_reasoning(self):
        output = [{"type": "reasoning", "id": "rs_1", "encrypted_content": "enc",
                   "summary": [{"type": "summary_text", "text": "Make the dough first."}]},
                  {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "place_topping",
                   "arguments": "{\"pizza\": 1}"}]
        calls, patch = self.capture({"output": output,
                                     "usage": {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13}})
        session = OpenAISession(SECRET, "gpt-5.4-nano")
        with patch:
            actions, usage = session.ask("prompt", self.tools)
            session.reply([{"ok": True}])
            session.ask("prompt", self.tools)
        body = calls[0]["body"]
        self.assertTrue(calls[0]["url"].endswith("/responses"))
        self.assertEqual(body["tools"][0], {"type": "function", "name": "place_topping", "description": "Place one topping.",
                                            "parameters": self.tools[0]["parameters"]})
        self.assertEqual((body["store"], body["parallel_tool_calls"]), (False, True))
        self.assertEqual(body["include"], ["reasoning.encrypted_content"])
        self.assertEqual(actions, [{"tool": "place_topping", "args": {"pizza": 1}}])
        self.assertEqual(session.last_output["reasoning"], "Make the dough first.")
        second = calls[1]["body"]["input"]
        self.assertEqual(second[1:3], output)
        self.assertEqual(second[3], {"type": "function_call_output", "call_id": "call_1", "output": "{\"ok\": true}"})
        self.assertEqual(usage["input"], 9)

    def test_anthropic_tool_results_keep_content(self):
        content = [{"type": "thinking", "thinking": "Spread first.", "signature": "s"},
                   {"type": "tool_use", "id": "toolu_1", "name": "place_topping", "input": {"pizza": 1}}]
        calls, patch = self.capture({"content": content, "stop_reason": "tool_use",
                                     "usage": {"input_tokens": 11, "output_tokens": 6,
                                               "cache_read_input_tokens": 2}})
        session = AnthropicSession(SECRET, "claude-haiku-5-5", effort="low")
        with patch:
            actions, usage = session.ask("prompt", self.tools)
            session.reply([{"ok": True}])
            session.ask("prompt", self.tools)
        body = calls[0]["body"]
        self.assertEqual(body["tools"][0]["input_schema"]["type"], "object")
        self.assertEqual(body["tool_choice"], {"type": "auto"})
        self.assertEqual(body["output_config"], {"effort": "low"})
        self.assertEqual(body["thinking"], {"type": "adaptive", "display": "summarized"})
        self.assertEqual(session.last_output["reasoning"], "Spread first.")
        self.assertEqual(calls[0]["headers"]["anthropic-version"], providers.ANTHROPIC_VERSION)
        second = calls[1]["body"]["messages"]
        self.assertEqual(second[1], {"role": "assistant", "content": content})
        self.assertEqual(second[2]["content"][0]["tool_use_id"], "toolu_1")
        self.assertEqual(actions, [{"tool": "place_topping", "args": {"pizza": 1}}])
        self.assertEqual(usage["input"], 13)
        self.assertNotIn(SECRET, json.dumps([c["body"] for c in calls]))

    def test_vllm_sends_card_sampling_and_keeps_reasoning(self):
        message = {"role": "assistant", "content": None, "reasoning_content": "plan the dough first",
                   "tool_calls": [{"id": "c1", "type": "function",
                                   "function": {"name": "place_topping", "arguments": "{\"pizza\": 1}"}}]}
        calls, patch = self.capture({"choices": [{"message": message}], "usage": {}})
        session = providers.VLLMSession("", "Qwen/Qwen3.6-27B", base_url="http://gpu:8000/v1",
                                        sampling={"temperature": 1.0, "top_k": 20},
                                        chat_template_kwargs={"preserve_thinking": True})
        with patch:
            session.ask("prompt", self.tools)
            session.reply([{"ok": True}])
            session.ask("prompt", self.tools)
        self.assertTrue(calls[0]["url"].startswith("http://gpu:8000/v1/chat/completions"))
        self.assertEqual(calls[0]["headers"], {})
        self.assertEqual((calls[0]["body"]["temperature"], calls[0]["body"]["top_k"]), (1.0, 20))
        self.assertEqual(calls[0]["body"]["chat_template_kwargs"], {"preserve_thinking": True})
        self.assertEqual(calls[1]["body"]["messages"][1]["reasoning_content"], "plan the dough first")

    def test_hosted_chat_services_do_not_send_reasoning_fields(self):
        message = {"role": "assistant", "content": "x", "reasoning_content": "hidden", "tool_calls": []}
        calls, patch = self.capture({"choices": [{"message": message}], "usage": {}})
        session = providers.MistralSession(SECRET, "some-model")
        with patch:
            session.ask("prompt", self.tools)
            session.reply([], idle="{}")
            session.ask("prompt", self.tools)
        self.assertNotIn("reasoning_content", calls[1]["body"]["messages"][1])

    def test_shared_reasoning_level_maps_to_each_service(self):
        _, patch = self.capture({"candidates": [{"content": {"parts": []}}], "output": [], "content": [],
                                 "stop_reason": "end_turn", "usage": {}})
        with patch as recorder:
            GeminiSession(SECRET, "gemini-3.1-flash-lite", reasoning_effort="low").ask("p", self.tools)
            OpenAISession(SECRET, "gpt-5.4-nano", reasoning_effort="low").ask("p", self.tools)
            AnthropicSession(SECRET, "claude-haiku-5-5", reasoning_effort="low").ask("p", self.tools)
        gemini, openai, anthropic = (call.kwargs.get("body") if "body" in call.kwargs else call.args[2]
                                     for call in recorder.call_args_list)
        self.assertEqual(gemini["generationConfig"]["thinkingConfig"]["thinkingLevel"], "low")
        self.assertEqual(openai["reasoning"], {"summary": "auto", "effort": "low"})
        self.assertEqual(anthropic["output_config"], {"effort": "low"})

    def test_anthropic_refusal_is_an_error(self):
        _, patch = self.capture({"content": [], "stop_reason": "refusal", "usage": {}})
        with patch, self.assertRaises(ProviderError):
            AnthropicSession(SECRET, "claude-haiku-5-5").ask("prompt", self.tools)

    def test_gemini_schema_keeps_supported_keywords(self):
        schema = gemini_schema({"type": "array", "items": {"type": "number"}, "minItems": 2,
                                "additionalProperties": False, "$schema": "x"})
        self.assertEqual(schema, {"type": "ARRAY", "items": {"type": "NUMBER"}, "minItems": 2})


class CredentialTest(unittest.TestCase):
    def write(self, data):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_family_names_and_environment_names_resolve(self):
        path = self.write({"gemini": "g", "gpt": "o", "ANTHROPIC_API_KEY": "a"})
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_api_keys(path), {"gemini": "g", "openai": "o", "anthropic": "a",
                                                   "mistral": "", "vllm": ""})

    def test_environment_wins_and_missing_key_message_has_no_values(self):
        path = self.write({"claude": SECRET})
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "from-env"}, clear=True):
            self.assertEqual(load_api_keys(path)["anthropic"], "from-env")
            with self.assertRaises(CredentialError) as raised:
                load_api_keys(path, required=["openai"])
        self.assertNotIn(SECRET, str(raised.exception))
        self.assertIn("OPENAI_API_KEY", str(raised.exception))


class CliTest(unittest.TestCase):
    def test_model_run_through_cli_saves_report(self):
        session = ScriptedSession(PLAN + [{"tool": "finish", "args": {}}])
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": SECRET}, clear=True), \
                mock.patch.object(providers, "SESSIONS", {"anthropic": lambda key, model, **_: session}), \
                mock.patch("sys.stdout"):
            output = Path(folder) / "run.json"
            code = cli_main(["--case", "practice_olive", "--ai-provider", "anthropic", "--request-interval", "0",
                             "--max-requests", "80", "--api-keys", str(Path(folder) / "none.json"),
                             "--output", str(output)])
            saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(saved["termination"], "finished")
        self.assertNotIn(SECRET, json.dumps(saved, ensure_ascii=False))

    def test_stdin_protocol_unchanged_without_model_flags(self):
        with mock.patch("sys.stdin", iter([])), mock.patch("sys.stdout") as stdout:
            self.assertEqual(cli_main(["--case", "practice_olive"]), 1)
        first = json.loads(stdout.write.call_args_list[0].args[0])
        self.assertEqual(first["event"], "ready")


if __name__ == "__main__":
    unittest.main()
