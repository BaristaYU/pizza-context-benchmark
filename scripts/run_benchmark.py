"""Run E2E kitchen batches or independent L-to-A Reasoning batches."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from threading import Event

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from pizzabench import ai_runner, reasoning  # noqa: E402
from pizzabench.batch_engine import run_batch  # noqa: E402
from pizzabench.credentials import KEY_FILE, CredentialError, load_api_keys  # noqa: E402
from pizzabench.data_io import read_jsonl  # noqa: E402
from pizzabench.english100 import DATA  # noqa: E402
from pizzabench.game_cli import REASONING_LEVELS, REASONING_PROVIDERS  # noqa: E402
from pizzabench.game_orders import PRACTICE, load_orders  # noqa: E402
from pizzabench.providers import PROVIDERS, ProviderError, RequestPacer, create_session  # noqa: E402


def select_cases(options):
    if options.task == "reasoning":
        orders = read_jsonl(options.data or DATA / "benchmark_cases.jsonl")
    else:
        orders = load_orders(options.data)
        if not options.include_practice:
            practice = {order["id"] for order in PRACTICE}
            orders = [order for order in orders if order["id"] not in practice]
    if options.cases:
        wanted = [value.strip() for value in options.cases.split(",") if value.strip()]
        by_id = {order["id"]: order for order in orders}
        missing = [case_id for case_id in wanted if case_id not in by_id]
        if missing:
            raise ValueError("Unknown case: " + ", ".join(missing))
        orders = [by_id[case_id] for case_id in wanted]
    return orders[:options.max_cases]


def session_options(options):
    values = {"timeout": options.request_timeout,
              **ai_runner.session_options_for(options.provider, options.model, base_url=options.base_url)}
    if options.reasoning_effort != "default" and options.provider in REASONING_PROVIDERS:
        values["reasoning_effort"] = options.reasoning_effort
    if options.provider == "anthropic":
        values["max_output_tokens"] = options.max_output_tokens
    return values


def estimate(cases, options, key, rules):
    """Optimistic and conservative cost for the selected cases without a model request."""
    session = create_session(options.provider, key, options.model, pacer=RequestPacer(0.3),
                             **session_options(options))
    rows = []
    try:
        for case in cases:
            report = ai_runner.estimate_session(case, session, rules=rules, max_requests=options.max_requests)
            rows.append({"case_id": case["id"], "reference_plan_calls": report["reference_plan_calls"],
                         "optimistic_usd": report["optimistic"]["total_usd"],
                         "conservative_usd": report["conservative"]["total_usd"],
                         "token_counting": report["token_counting"]})
    finally:
        session.close()
    priced = all(row["optimistic_usd"] is not None for row in rows)
    return {"provider": options.provider, "model": options.model, "cases": len(rows),
            "optimistic_usd": round(sum(r["optimistic_usd"] for r in rows), 6) if priced else None,
            "conservative_usd": round(sum(r["conservative_usd"] for r in rows), 6) if priced else None,
            "assumption": "낙관: 참조 계획대로 한 턴에 한 호출 · 보수: 요청 상한까지 사용하고 턴마다 최대 응답과 추론 토큰",
            "rows": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pizza Context Benchmark batch runner")
    parser.add_argument("--task", choices=["e2e", "reasoning"], default="e2e")
    parser.add_argument("--provider", choices=list(PROVIDERS), default="gemini")
    parser.add_argument("--model", help="Exact model ID; defaults to configs/agent_models.json")
    parser.add_argument("--data", type=Path, help="Q-SLATE JSONL; default is the English 100 set")
    parser.add_argument("--cases", help="Comma-separated case IDs, in order")
    parser.add_argument("--include-practice", action="store_true", help="Also run the four Korean practice orders")
    parser.add_argument("--api-keys", type=Path, default=KEY_FILE)
    parser.add_argument("--base-url", help="vLLM server address; default from configs/agent_models.json")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--estimate-cost", action="store_true", help="Print a cost estimate and exit")
    parser.add_argument("--rules", action="store_true", help="Put docs/pizza_domain_rules.md before the ready event")
    parser.add_argument("--max-cases", type=int, default=10)
    parser.add_argument("--max-requests", type=int, default=60)
    parser.add_argument("--max-tools", type=int, default=150)
    parser.add_argument("--max-seconds", type=int, default=900)
    parser.add_argument("--max-cost", type=float, help="USD budget per case")
    parser.add_argument("--max-total-cost", type=float, help="USD budget for this invocation")
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--reasoning-effort", choices=["default", *REASONING_LEVELS], default="medium")
    parser.add_argument("--request-interval", type=float, default=3)
    parser.add_argument("--request-timeout", type=float, default=60)
    options = parser.parse_args(argv)
    if min(options.max_cases, options.max_requests, options.max_tools, options.max_seconds) < 1:
        parser.error("Limits must be positive")
    if options.resume and options.output_dir:
        parser.error("--resume and --output-dir are mutually exclusive")
    is_reasoning = options.task == "reasoning"
    if is_reasoning and (options.rules or options.include_practice):
        parser.error("--rules and --include-practice apply to E2E")
    stop = Event()

    def progress(event):
        if event["kind"] == "batch_progress":
            report = event["report"]
            cost = (report.get("cost") or {}).get("total_usd")
            print(f"[{event['index']}/{event['total']}] {event['case_id']} {report['termination']} "
                  f"passed={bool((report.get('score') or {}).get('passed'))} preserved={event['preserved']} "
                  f"requests={report.get('requests', 0)} cost={'-' if cost is None else f'${cost:.4f}'}", flush=True)

    try:
        config = ai_runner.load_config()
        options.model = options.model or config["default_models"].get(options.provider)
        if not options.model:
            raise ValueError("--model을 지정하세요.")
        cases = select_cases(options)
        if is_reasoning and options.estimate_cost:
            print(json.dumps(reasoning.estimate_cost(cases, options.provider, options.model, config),
                             ensure_ascii=False, indent=2))
            return 0
        required = [] if options.provider == "vllm" else [options.provider]
        key = load_api_keys(options.api_keys, required=required)[options.provider]
        rules = ai_runner.read_rules() if options.rules else None
        if options.estimate_cost:
            print(json.dumps(estimate(cases, options, key, rules), ensure_ascii=False, indent=2))
            return 0
        output_root = REPO.parent / "pizza-benchmark-results" if is_reasoning else REPO / "results"
        prefix = "reasoning" if is_reasoning else "run"
        folder = options.resume or options.output_dir or output_root / datetime.now().strftime(f"{prefix}_%Y%m%d_%H%M%S_%f")
        result = run_batch(cases, options.provider, options.model, key, folder, resume=bool(options.resume),
                           request_interval=options.request_interval, max_requests=options.max_requests,
                           max_tools=options.max_tools, max_seconds=options.max_seconds,
                           max_cost_usd=options.max_cost, max_total_cost_usd=options.max_total_cost,
                           rules=rules, session_options=session_options(options), stop=stop,
                           on_event=progress, config=config, task=options.task)
    except (CredentialError, ValueError, ProviderError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("입력 파일 또는 결과 폴더를 확인하세요.", file=sys.stderr)
        return 2
    summary = result["summary"]
    print(f"passed {summary['passed']}/{summary['attempted']} · stop={summary.get('batch_stop_reason')} "
          f"· estimated ${summary.get('cumulative_cost_usd', 0):.4f}", flush=True)
    if is_reasoning:
        print(f"format_errors={summary['format_errors']} · condition_mismatches={summary['condition_mismatches']}", flush=True)
        print("SUMMARY " + str(Path(result["folder"]) / "summary.json"), flush=True)
    else:
        print("REPORT " + str(Path(result["folder"]) / "report.html"), flush=True)
    return 130 if stop.is_set() else 0


if __name__ == "__main__":
    raise SystemExit(main())
