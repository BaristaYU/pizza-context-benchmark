"""Run a model against the mock kitchen through the same tool protocol as the CLI.

The model sees only what ``ToolEnvironment.ready`` exposes: the customer order, the
observable state and the tool list. Reference answers and plans stay
on the grading side, exactly as in the stdin/stdout session.
"""

import json
from copy import deepcopy
from pathlib import Path
from threading import Event
from time import monotonic

from .game_cli import ToolEnvironment
from .kitchen import observable_state


CONFIG_FILE = Path(__file__).resolve().parent.parent / "configs" / "agent_models.json"
TERMINATION = {"finished", "cancelled", "time_limit", "tool_limit", "tool_error_limit", "request_limit",
               "cost_limit", "api_error"}

# The first message is the CLI's ready event, so a model starts from exactly what a stdin
# client sees. No task instruction is added; the tool list travels in the API's tool field.
PROMPT_FORMAT = "cli-ready-event-v1"


def load_config(path=None):
    path = Path(path) if path is not None else CONFIG_FILE
    return json.loads(path.read_text(encoding="utf-8-sig"))


def model_price(provider, model, config=None):
    """Published price per 1M tokens, or None when the model is not in the table."""
    config = config or load_config()
    return (config.get("pricing", {}).get(provider) or {}).get(model)


def usage_total(usages):
    totals = {"input": 0, "output": 0, "total": 0}
    for usage in usages:
        for key in totals:
            totals[key] += int(usage.get(key) or 0)
    return totals


def cost_of(usages, provider, model, config=None):
    """Convert recorded usage into USD with the cached published prices."""
    totals = usage_total(usages)
    price = model_price(provider, model, config)
    if not price:
        return {**totals, "priced": False, "input_usd": None, "output_usd": None, "total_usd": None,
                "price_per_mtok": None}
    input_usd = totals["input"] / 1_000_000 * price["input"]
    output_usd = totals["output"] / 1_000_000 * price["output"]
    return {**totals, "priced": True, "input_usd": round(input_usd, 6), "output_usd": round(output_usd, 6),
            "total_usd": round(input_usd + output_usd, 6),
            "price_per_mtok": {"input": price["input"], "output": price["output"]}}


def build_prompt(ready, *, rules=None):
    """The game's own ready event: order, observable state and, for Tool Use, the given plan.

    ``rules`` is an explicit experiment condition that puts a rules document before the
    event. It is off unless a run asks for it.
    """
    event = {key: value for key, value in ready.items() if key != "tools"}
    text = json.dumps(event, ensure_ascii=False)
    return rules + "\n\n" + text if rules else text


def idle_message(environment):
    """Sent when a reply has no tool call: the current observation, as observe would return."""
    event = {"event": "observation", **observable_state(environment.session.observe())}
    return json.dumps(event, ensure_ascii=False)


def read_rules(path=None):
    path = Path(path) if path is not None else Path(__file__).resolve().parent.parent / "docs" / "pizza_domain_rules.md"
    return path.read_text(encoding="utf-8-sig")


def safe_error(exc):
    """Classify a failure without exporting request bodies or credentials."""
    code = getattr(exc, "code", None)
    code = code if isinstance(code, int) and 100 <= code <= 599 else None
    text = str(exc).lower()
    if code in {401, 403}:
        detail = "API 키 인증 또는 모델 사용 권한을 확인하세요."
    elif code == 404:
        detail = "선택한 모델을 찾을 수 없습니다. 모델 목록을 다시 확인하세요."
    elif code == 429:
        detail = "요청 또는 토큰 한도입니다. 서비스 계정의 할당량과 잔액을 확인하세요."
    elif code == 400:
        detail = "서비스가 요청 형식을 거부했습니다. 모델과 도구 정의를 확인하세요."
    elif code and code >= 500:
        detail = "서비스 서버 오류입니다. 잠시 후 다시 시도하세요."
    elif "timed out" in text or "timeout" in text:
        detail = "응답 대기 시간을 초과했습니다."
    else:
        detail = "서비스 연결 오류입니다. 네트워크와 모델 사용 권한을 확인하세요."
    return (f"HTTP {code} · " if code else "") + detail


def run_agent(order, session, *, oven_seconds=6,
              reference_plan=None, rules=None, max_requests=60, max_tools=150, max_seconds=900,
              max_consecutive_errors=5, max_cost_usd=None, stop=None, on_event=None,
              config=None, environment=None, execute=None):
    """Play one order. ``environment`` and ``execute`` let a window run the tool calls on its
    own thread and draw the same kitchen; by default the runner owns both."""
    stop = stop or Event()
    started = monotonic()
    config = config or load_config()
    provider, model = getattr(session, "provider", "unknown"), getattr(session, "model", None)
    if max_cost_usd is not None and not model_price(provider, model, config):
        raise ValueError(f"{model}의 단가가 configs/agent_models.json에 없어 비용 한도를 적용할 수 없습니다")
    if environment is None:
        environment = ToolEnvironment(order, oven_seconds=oven_seconds, reference_plan=reference_plan)
    execute = execute or environment.request
    ready = environment.ready()
    tools = ready["tools"]
    prompt = build_prompt(ready, rules=rules)
    usages, records = [], []
    requests = consecutive_errors = 0
    reason, error, error_code = "request_limit", None, None

    def elapsed():
        return monotonic() - started

    turns = []

    def emit():
        if on_event:
            on_event({"records": deepcopy(records), "requests": requests, "turns": deepcopy(turns)})

    try:
        while requests < max_requests:
            if stop.is_set():
                reason = "cancelled"
                break
            if elapsed() >= max_seconds:
                reason = "time_limit"
                break
            # The budget is checked before each request, so a run stops after the request
            # that crosses it; it cannot stop a request that is already being generated.
            if max_cost_usd is not None and cost_of(usages, provider, model, config)["total_usd"] >= max_cost_usd:
                reason = "cost_limit"
                break
            requests += 1
            actions, usage = session.ask(prompt, tools)
            usages.append(usage)
            # What the model returned this turn, for monitoring: reasoning summary, text and calls.
            output = getattr(session, "last_output", None) or {}
            turn = {"request": requests, "reasoning": output.get("reasoning") or "", "text": output.get("text") or "",
                    "reasoning_scope": output.get("reasoning_scope"), "raw_reply": output.get("raw"),
                    "calls": [], "usage": {key: usage.get(key) for key in ("input", "output", "total")}}
            turns.append(turn)
            emit()
            if stop.is_set():
                reason = "cancelled"
                break
            results = []
            for action in actions:
                if len(records) >= max_tools:
                    reason = "tool_limit"
                    break
                if elapsed() >= max_seconds:
                    reason = "time_limit"
                    break
                command = {"tool": action.get("tool"), "args": action.get("args")}
                if command["args"] is None:
                    command = {"tool": action.get("tool")}
                response = execute(json.dumps(command, ensure_ascii=False, allow_nan=False))
                records.append({"tool": action.get("tool"), "args": deepcopy(action.get("args")),
                                "response": deepcopy(response)})
                turn["calls"].append(records[-1])
                results.append(response)
                consecutive_errors = 0 if response.get("ok") else consecutive_errors + 1
                emit()
                if response.get("done"):
                    reason = "finished"
                    break
                if consecutive_errors >= max_consecutive_errors:
                    reason = "tool_error_limit"
                    break
            if reason in TERMINATION - {"request_limit"}:
                break
            session.reply(results, idle=None if actions else idle_message(environment))
    except Exception as exc:  # provider, cancellation and serialisation failures share one exit
        if stop.is_set() or type(exc).__name__ == "CancelledRequest":
            reason = "cancelled"
        else:
            reason = "api_error"
            code = getattr(exc, "code", None)
            error_code = code if isinstance(code, int) and 100 <= code <= 599 else None
            error = safe_error(exc)

    report = environment.report()
    evaluation = report.get("evaluation")
    score = deepcopy(report.get("score"))
    if reason != "finished" and isinstance(score, dict):
        score["passed"] = False
    return {"case_id": order["id"], "environment_version": report["environment_version"],
            "task": report["task"], "mode": f"{provider} {report['task']}", "provider": provider, "model": model,
            "model_settings": deepcopy(getattr(session, "settings", {})),
            "state": deepcopy(report["state"]), "clarified": report["clarified"],
            "execution": report["execution"], "evaluation": evaluation, "score": score,
            "tool_calling": [{"tool": record["tool"], "args": record["args"]} for record in records],
            "records": records, "turns": turns, "interactions": report["interactions"],
            "protocol_errors": report["protocol_errors"], "request_errors": report["request_errors"],
            "termination": reason, "error": error, "error_code": error_code, "requests": requests,
            "usage": usages, "cost": cost_of(usages, provider, model, config),
            "elapsed_seconds": round(elapsed(), 3), "prompt_characters": len(prompt),
            "limits": {"requests": max_requests, "tools": max_tools, "seconds": max_seconds,
                       "consecutive_errors": max_consecutive_errors, "cost_usd": max_cost_usd},
            "rules_included": bool(rules)}


def summarise(result):
    """The short record printed after a run; the full record goes to --output."""
    score = result.get("score") or {}
    return {"case_id": result["case_id"], "provider": result["provider"], "model": result["model"],
            "task": result["task"], "termination": result["termination"], "error": result["error"],
            "requests": result["requests"], "tool_calls": len(result["tool_calling"]),
            "tool_errors": result["request_errors"], "passed": score.get("passed"),
            "clarified": result["clarified"],
            "usage": {key: result["cost"][key] for key in ("input", "output", "total")},
            "cost_usd": result["cost"]["total_usd"], "elapsed_seconds": result["elapsed_seconds"]}


def reference_plan_for(order, state):
    """Reuse the verified reference planner so an estimate reflects real tool traffic."""
    from .english100 import plan_from_answer
    return plan_from_answer(order["answer"], state)


def conversation_profile(order, plan, **environment_options):
    """Replay a plan offline and measure what each turn would add to the conversation."""
    environment = ToolEnvironment(order, **environment_options)
    turns = []
    for action in list(plan) + [{"tool": "finish", "args": {}}]:
        command = {"tool": action["tool"], "args": action.get("args") or {}}
        text = json.dumps(command, ensure_ascii=False)
        response = environment.request(text)
        reply = json.dumps(response, ensure_ascii=False)
        turns.append({"call": len(text), "response": len(reply), "ok": bool(response.get("ok")),
                      "text": text + "\n" + reply})
    return turns


# Used only when a service has no free token counter (OpenAI). Both sit above the densities
# measured with Gemini countTokens on this prompt (0.26 per character for the prompt and
# 0.34 for tool JSON), so the fallback errs toward a higher estimate.
FALLBACK_TOKENS_PER_CHARACTER = {"prompt": 0.30, "conversation": 0.40}


def scenario(base_tokens, turns, *, ratio, reasoning_tokens, price):
    """Every request resends the prompt and all earlier turns; sum that, then price it."""
    carried = 0
    input_tokens = output_tokens = 0
    for turn in turns:
        input_tokens += base_tokens + int(carried * ratio)
        carried += turn["call"] + turn["response"]
        output_tokens += int(turn["call"] * ratio) + reasoning_tokens
    count = len(turns)
    value = {"turns": count, "input": input_tokens, "output": output_tokens,
             "total": input_tokens + output_tokens, "reasoning_tokens_per_turn": reasoning_tokens}
    if not price:
        return {**value, "priced": False, "total_usd": None}
    cost = input_tokens / 1_000_000 * price["input"] + output_tokens / 1_000_000 * price["output"]
    return {**value, "priced": True, "input_usd": round(input_tokens / 1_000_000 * price["input"], 6),
            "output_usd": round(output_tokens / 1_000_000 * price["output"], 6), "total_usd": round(cost, 6)}


def estimate_session(order, session, plan=None, *, rules=None, config=None, max_requests=60,
                     reasoning_tokens=400, oven_seconds=6):
    """Predict tokens and cost for one order without sending a generation request.

    The optimistic case assumes the model plays the verified reference plan with one tool
    call per turn. The conservative case assumes it uses every allowed request and that each
    turn carries the largest response seen plus a reasoning allowance. The prompt and the
    replayed conversation are counted with the service's free token counter when it has one.
    """
    config = config or load_config()
    environment_options = {"oven_seconds": oven_seconds}
    environment = ToolEnvironment(order, reference_plan=plan, **environment_options)
    ready = environment.ready()
    prompt = build_prompt(ready, rules=rules)
    tools = ready["tools"]
    base_chars = len(prompt) + len(json.dumps(tools, ensure_ascii=False))
    plan = list(plan) if plan is not None else reference_plan_for(order, environment.session.kitchen.snapshot())
    turns = conversation_profile(order, plan, **environment_options)
    sample = "\n".join(turn["text"] for turn in turns)
    try:
        base_tokens, counting = session.count_tokens(prompt, tools), "provider endpoint"
        ratio = session.count_tokens(sample, []) / len(sample)
    except Exception:
        base_tokens = int(base_chars * FALLBACK_TOKENS_PER_CHARACTER["prompt"])
        ratio, counting = FALLBACK_TOKENS_PER_CHARACTER["conversation"], "fallback ratio"
    worst = max(turn["response"] for turn in turns)
    call = max(turn["call"] for turn in turns)
    provider, model = getattr(session, "provider", "unknown"), getattr(session, "model", None)
    price = model_price(provider, model, config)
    heavy = [{"call": call, "response": worst} for _ in range(max_requests)]
    return {"case_id": order["id"], "provider": provider, "model": model, "price_per_mtok": price,
            "token_counting": counting, "base_prompt_characters": base_chars, "base_prompt_tokens": base_tokens,
            "conversation_tokens_per_character": round(ratio, 4),
            "reference_plan_calls": len(plan), "rules_included": bool(rules),
            "optimistic": scenario(base_tokens, turns, ratio=ratio, reasoning_tokens=0, price=price),
            "conservative": scenario(base_tokens, heavy, ratio=ratio, reasoning_tokens=reasoning_tokens, price=price),
            "assumptions": {"optimistic": "모델이 참조 계획과 같은 호출을 한 턴에 하나씩 수행하고 추론 토큰이 없는 경우",
                            "conservative": f"허용된 {max_requests}요청을 모두 사용하고 매 턴 가장 큰 응답과 "
                                            f"추론 {reasoning_tokens}토큰이 붙는 경우"}}


def session_options_for(provider, model, config=None, *, base_url=None):
    """Per-model settings kept in configs/agent_models.json, such as a local model's sampling."""
    if provider != "vllm":
        return {}
    config = config or load_config()
    local = config.get("local_models") or {}
    entry = (local.get("models") or {}).get(model) or {}
    return {"base_url": base_url or local.get("base_url"), "sampling": entry.get("sampling"),
            "chat_template_kwargs": entry.get("chat_template_kwargs")}
