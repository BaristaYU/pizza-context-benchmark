"""Shared request, format error and usage handling for one-response evaluations."""

import json
from math import ceil
import re
from time import monotonic

from . import ai_runner
from .game_cli import read_json
from .providers import CancelledRequest, ProviderError


def parse_response(text, *, actions=()):
    if actions:
        raise ValueError("The model returned a tool call instead of JSON")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The model returned no JSON text")
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced[1]
    try:
        return read_json(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    except RecursionError as exc:
        raise ValueError("The JSON answer is nested too deeply") from exc


def format_error(message):
    return {"status": "format_error", "passed": False, "errors": [str(message)], "differences": {}}


def run_case(case, session, *, task, scoring_version, prompt_for, assess, input_stage=None,
             stop=None, max_cost_usd=None, config=None):
    started = monotonic()
    report = {"case_id": case["id"], "task": task, "scoring_version": scoring_version,
              "model": session.model, "provider": session.provider,
              "model_settings": dict(session.settings), "requests": 0, "score": None,
              "error": None, "error_code": None, "usage": [],
              "limits": {"requests": 1, "cost_usd": max_cost_usd}}
    if input_stage is not None:
        report["input_stage"] = input_stage
    if stop is not None and stop.is_set():
        report["termination"] = "cancelled"
    elif max_cost_usd is not None and max_cost_usd <= 0:
        report["termination"] = "cost_limit"
    else:
        prompt = prompt_for(case)
        report.update(requests=1, prompt_characters=len(prompt))
        try:
            actions, usage = session.ask(prompt, [])
        except CancelledRequest:
            report["termination"] = "cancelled"
        except ProviderError as exc:
            report.update(termination="api_error", error=ai_runner.safe_error(exc), error_code=exc.code)
        else:
            output = session.last_output
            text = output.get("text")
            report.update(termination="finished", response_text=text, raw_reply=output.get("raw"), usage=[usage])
            report.update(assess(case, text, actions=actions))
    report["cost"] = ai_runner.cost_of(report["usage"], session.provider, session.model, config)
    report["elapsed_seconds"] = round(monotonic() - started, 3)
    return report


def estimate_cost(cases, provider, model, config=None, *, task, prompt_for, reference_for):
    """Estimate one response per case using local character counts and cached prices."""
    config = config or ai_runner.load_config()
    ratio = ai_runner.FALLBACK_TOKENS_PER_CHARACTER
    rows = []
    for case in cases:
        input_tokens = ceil(len(prompt_for(case)) * ratio["prompt"])
        answer_tokens = ceil(len(json.dumps(reference_for(case), ensure_ascii=False)) * ratio["conversation"])
        optimistic = ai_runner.cost_of([{"input": input_tokens, "output": answer_tokens}], provider, model, config)
        conservative = ai_runner.cost_of([{"input": input_tokens, "output": answer_tokens + 400}], provider, model, config)
        rows.append({"case_id": case["id"], "optimistic_usd": optimistic["total_usd"],
                     "conservative_usd": conservative["total_usd"], "input_tokens": input_tokens,
                     "answer_tokens": answer_tokens})
    priced = all(row["optimistic_usd"] is not None for row in rows)
    return {"task": task, "provider": provider, "model": model, "cases": len(cases),
            "optimistic_usd": round(sum(row["optimistic_usd"] for row in rows), 6) if priced else None,
            "conservative_usd": round(sum(row["conservative_usd"] for row in rows), 6) if priced else None,
            "assumption": "One request per case; character-based estimates with 400 extra output tokens in the conservative estimate",
            "rows": rows}
