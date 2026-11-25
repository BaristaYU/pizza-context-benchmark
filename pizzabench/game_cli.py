"""Persistent JSONL tool environment: python -m pizzabench.game_cli."""

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

from .menu import menu
from .environment import ToolError
from .execution_eval import validate_plan
from .game import GameSession, run_plan
from .game_orders import load_orders
from .kitchen import MAX_TOPPING_POINTS, Kitchen, observable_state


# Version 2 returned S with coating coverage instead of the internal grid and undo history.
# Version 3 follows kitchen v3 and answers an action with the changed pizza only; the full S,
# including every topping coordinate, comes from observe.
PROTOCOL_VERSION = "pizza-tools-jsonl-4"
DEFAULT_KEY_FILE = Path(__file__).resolve().parent.parent / "configs" / "api_keys.local.json"
# Levels all three paid services accept: Gemini thinkingLevel, OpenAI reasoning.effort, Claude effort.
REASONING_LEVELS = ("low", "medium", "high")
REASONING_PROVIDERS = {"gemini", "openai", "anthropic"}


def read_json(text):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"Duplicate JSON key: {key}")
            value[key] = item
        return value

    def constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("JSON number is out of range")
        return parsed

    return json.loads(text, object_pairs_hook=unique, parse_constant=constant, parse_float=finite_float)


def action_result(tool, result):
    """The changed pizza without its topping coordinates; observe returns the full S."""
    if tool == "observe" or not isinstance(result, dict) or "pieces" not in result:
        return result
    return {key: value for key, value in result.items() if key != "pieces"}


def tool_definitions(kitchen, *, allow_clarification=True):
    """Portable JSON Schema tool descriptions, with no provider dependency."""
    pizza = {"type": "integer", "minimum": 1, "description": "Existing pizza ID returned by create."}
    point = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}
    descriptions = {
        "create": "Create dough and return its pizza ID.",
        "spread": "Spread dough at the preparation board before adding ingredients.",
        "paint": "Apply sauce or cheese along a stroke, sampled every 1/4.5 pizza radii. Coordinates: x right, y down. Whole coverage costs one portion; repainting costs nothing.",
        "fill": "Fill the selected whole/left/right region with sauce or cheese using the same helper as the GUI. No points argument is needed.",
        "place_toppings": "Place topping pieces of one kind, one piece per point. Each point must be within radius 0.86 of (0,0).",
        "bake": "Bake a spread pizza once; it lands on the cutting board, which holds one pizza. Bake a pizza on the board again for another pass.",
        "cut": "Add a center-crossing diameter cut at angle in degrees. Three different lines make six slices; duplicate lines do not add slices.",
        "serve": "Box a baked pizza from the cutting board. Box all pizzas, then call finish to deliver the order.",
        "undo": "Undo the last ingredient action on this pizza at the preparation board.",
        "discard": "Discard this pizza without refunding ingredients. A baking pizza must finish first.",
        "observe": "Read the current environment state without revealing the reference answer.",
    }
    fields = {
        "create": {"dough": {"type": "string", "enum": kitchen.registry["dough"]}},
        "spread": {"pizza": pizza},
        "paint": {"pizza": pizza, "item": {"type": "string", "enum": ["sauce", "cheese"]},
                  "kind": {"type": "string", "enum": kitchen.registry["sauce"], "description": "Required for sauce; omit for cheese."},
                  "points": {"type": "array", "items": point, "minItems": 1, "maxItems": 2048},
                  "region": {"type": "string", "enum": ["whole", "left", "right"], "description": "Optional clipping mask, default whole."}},
        "place_toppings": {"pizza": pizza, "kind": {"type": "string", "enum": kitchen.registry["topping"]},
                           "points": {"type": "array", "items": point, "minItems": 1, "maxItems": MAX_TOPPING_POINTS}},
        "cut": {"pizza": pizza, "angle": {"type": "number"}},
        **{tool: {"pizza": pizza} for tool in ["bake", "serve", "undo", "discard"]},
        "observe": {},
    }
    tools = []
    fields["fill"] = {k:deepcopy(v) for k,v in fields["paint"].items() if k != "points"}
    for name, (required, _) in kitchen.ACTIONS.items():
        tools.append({"name": name, "description": descriptions[name],
                      "parameters": {"type": "object", "properties": deepcopy(fields[name]),
                                     "required": sorted(required), "additionalProperties": False}})
    for name, description in ([
        ("clarify", "Reveal this order's clarification once. Only available in order-execution mode.")
    ] if allow_clarification else []) + [
        ("finish", "Deliver the boxed pizzas and end the session. Return the final evaluation; no further actions are accepted.")
    ]:
        tools.append({"name": name, "description": description,
                      "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}})
    return tools


class ToolEnvironment:
    def __init__(self, order, *, oven_seconds=6, reference_plan=None):
        if reference_plan is not None:
            validate_plan(reference_plan)
            # Verify the GT plan in an independent environment before exposing it.
            if not run_plan(order, reference_plan, oven_seconds=oven_seconds)["score"]["passed"]:
                raise ValueError("Reference plan does not satisfy this order")
        self.session = GameSession(order, oven_seconds=oven_seconds, reference_plan=reference_plan)
        self.interactions = []

    @property
    def fixed_plan(self):
        return self.session.reference_plan is not None

    def ready(self):
        observation = observable_state(self.session.observe())
        if self.fixed_plan:
            observation = {"state": observation["state"]}
        ready = {"event": "ready", "protocol": PROTOCOL_VERSION,
                 "task": "tool_use" if self.fixed_plan else "order_execution",
                 "environment_version": self.session.kitchen.version,
                 "observation": observation,
                 **({} if self.fixed_plan else {"menu": menu()}),
                 "tools": tool_definitions(self.session.kitchen, allow_clarification=not self.fixed_plan)}
        if self.fixed_plan:
            ready["plan"] = deepcopy(self.session.reference_plan)
        return ready

    def request(self, text):
        request_id = None
        command = None
        try:
            command = read_json(text)
            if not isinstance(command, dict) or set(command) - {"id", "tool", "args"}:
                raise ValueError("Request must contain tool, optional args and optional id")
            request_id = command.get("id")
            if request_id is not None and type(request_id) not in (str, int):
                raise ValueError("id must be a string or integer")
            tool, args = command.get("tool"), command.get("args", {})
            if not isinstance(tool, str) or not isinstance(args, dict):
                raise ValueError("tool must be a string and args must be an object")
        except (ValueError, TypeError) as exc:
            response = {"ok": False, "error_type": "invalid_request", "error": str(exc), "done": False}
        else:
            try:
                if self.session.finished:
                    raise ToolError("This session has finished")
                if self.fixed_plan and tool == "clarify":
                    raise ToolError("Clarification is not part of independent Tool Use")
                if tool == "finish":
                    if args:
                        raise ToolError("finish takes no arguments")
                    self.session.finish()
                    result = deepcopy(self.session.evaluation)
                else:
                    result = action_result(tool, observable_state(self.session.call(tool, args)))
                response = {"ok": True, "tool": tool, "result": result, "done": self.session.finished}
            except ToolError as exc:
                response = {"ok": False, "tool": tool, "error_type": "tool_error",
                            "error": str(exc), "done": self.session.finished}
        if request_id is not None:
            response["id"] = request_id
        self.interactions.append({"request": command, "response": deepcopy(response)})
        return response

    def report(self):
        report = self.session.report()
        report.update(protocol=PROTOCOL_VERSION, task="tool_use" if self.fixed_plan else "order_execution",
                      status="COMPLETE" if self.session.finished else "INCOMPLETE",
                      interactions=deepcopy(self.interactions))
        report["protocol_errors"] = sum(r["response"].get("error_type") == "invalid_request" for r in self.interactions)
        report["request_errors"] = sum(not r["response"]["ok"] for r in self.interactions)
        return report


def serve(environment, stdin, stdout):
    def emit(value):
        stdout.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        stdout.flush()

    emit(environment.ready())
    for text in stdin:
        if not text.strip():
            continue
        response = environment.request(text)
        emit(response)
        if response["done"]:
            return 0 if environment.session.evaluation["passed"] else 1
    emit({"event": "end", "status": "INCOMPLETE", "finished": False})
    return 1


def model_options(options):
    """Session settings shared by the model run and the cost estimate."""
    settings = {"timeout": options.request_timeout}
    if options.reasoning_effort != "default" and options.ai_provider in REASONING_PROVIDERS:
        settings["reasoning_effort"] = options.reasoning_effort
    if options.ai_provider == "anthropic":
        settings["max_output_tokens"] = options.max_output_tokens
    elif options.ai_provider == "openai" and options.max_output_tokens != 8192:
        # OpenAI keeps the model default unless a different cap is requested explicitly.
        settings["max_output_tokens"] = options.max_output_tokens
    return settings


def run_model(order, plan, options):
    """Let a model play this order through the same tool protocol as stdin/stdout."""
    # Imported here because the runner builds on ToolEnvironment from this module.
    from . import ai_runner
    from .credentials import load_api_keys
    from .providers import ProviderError, RequestPacer, create_session, list_models

    try:
        return model_session(order, plan, options, ai_runner, load_api_keys,
                             create_session, RequestPacer, list_models)
    except ProviderError as exc:
        raise ValueError(f"모델 서비스 오류: {exc}") from None


def model_session(order, plan, options, ai_runner, load_api_keys, create_session, RequestPacer, list_models):
    config = ai_runner.load_config()
    provider = options.ai_provider
    keys = load_api_keys(options.api_keys, required=[] if provider == "vllm" else [provider])
    model = options.ai_model or config["default_models"].get(provider)
    if not model:
        raise ValueError(f"{provider}에는 기본 모델이 없습니다. --ai-model로 모델 ID를 지정하세요.")
    if options.list_models:
        print(json.dumps(list_models(provider, keys[provider], base_url=options.base_url), ensure_ascii=False, indent=2))
        return 0
    extra = ai_runner.session_options_for(provider, model, config, base_url=options.base_url)
    session = create_session(provider, keys[provider], model,
                             pacer=RequestPacer(options.request_interval), **model_options(options), **extra)
    rules = ai_runner.read_rules() if options.rules else None
    if options.estimate_cost:
        report = ai_runner.estimate_session(order, session, plan, rules=rules, config=config,
                                            oven_seconds=options.oven_seconds,
                                            max_requests=options.max_requests)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    result = ai_runner.run_agent(order, session, oven_seconds=options.oven_seconds, reference_plan=plan, rules=rules,
                                 max_requests=options.max_requests, max_tools=options.max_tools,
                                 max_seconds=options.max_seconds, max_cost_usd=options.max_cost,
                                 config=config)
    session.close()
    if options.output:
        with options.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    print(json.dumps(ai_runner.summarise(result), ensure_ascii=False, indent=2))
    return 0 if result["score"] and result["score"]["passed"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Persistent pizza tool environment over JSONL stdin/stdout")
    parser.add_argument("--case", default="practice_olive")
    parser.add_argument("--data", type=Path, help="Additional Q-SLATE JSONL cases")
    parser.add_argument("--reference-plan", type=Path, help="Verified concrete plan for independent Tool Use")
    parser.add_argument("--oven-seconds", type=float, default=6)
    parser.add_argument("--output", type=Path, help="Save a new execution report; existing files are rejected")
    parser.add_argument("--list-tools", action="store_true")
    parser.add_argument("--list-cases", action="store_true")
    model = parser.add_argument_group("model session",
                                      "Let an API model play the order instead of reading stdin")
    model.add_argument("--ai-provider", choices=["gemini", "openai", "anthropic", "mistral", "vllm"],
                       help="Run this order with a model from the chosen service")
    model.add_argument("--ai-model", help="Exact model ID; defaults to configs/agent_models.json")
    model.add_argument("--api-keys", type=Path, default=DEFAULT_KEY_FILE,
                       help="Key file; environment variables take priority")
    model.add_argument("--list-models", action="store_true", help="Print the account's models and exit")
    model.add_argument("--base-url", help="vLLM server address; default from configs/agent_models.json")
    model.add_argument("--estimate-cost", action="store_true",
                       help="Report token and cost estimates without sending a model request")
    model.add_argument("--rules", action="store_true",
                       help="Put docs/pizza_domain_rules.md before the ready event (off by default)")
    model.add_argument("--max-cost", type=float, help="Stop before the next request once this many USD are used")
    model.add_argument("--max-requests", type=int, default=60)
    model.add_argument("--max-tools", type=int, default=150)
    model.add_argument("--max-seconds", type=float, default=900)
    model.add_argument("--max-output-tokens", type=int, default=8192)
    model.add_argument("--reasoning-effort", choices=["default", *REASONING_LEVELS], default="medium",
                       help="Same reasoning level for Gemini, OpenAI and Anthropic; 'default' leaves each model's own")
    model.add_argument("--request-interval", type=float, default=3, help="Seconds between request starts")
    model.add_argument("--request-timeout", type=float, default=60)
    options = parser.parse_args(argv)
    try:
        if options.list_tools:
            print(json.dumps(tool_definitions(Kitchen()), ensure_ascii=False, indent=2))
            return 0
        orders = load_orders(options.data)
        if options.list_cases:
            print(json.dumps([{"id": r["id"], "label": r["label"]} for r in orders], ensure_ascii=False, indent=2))
            return 0
        order = next((r for r in orders if r["id"] == options.case), None)
        if order is None:
            raise ValueError(f"Unknown case: {options.case}")
        if options.output and (options.output.exists() or not options.output.parent.is_dir()):
            raise ValueError("Output must be a new file in an existing directory")
        plan = None if options.reference_plan is None else read_json(options.reference_plan.read_text(encoding="utf-8-sig"))
        if options.ai_provider:
            return run_model(order, plan, options)
        environment = ToolEnvironment(order, oven_seconds=options.oven_seconds, reference_plan=plan)
        result = serve(environment, sys.stdin, sys.stdout)
        if options.output:
            with options.output.open("x", encoding="utf-8") as handle:
                json.dump(environment.report(), handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
        return result
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
