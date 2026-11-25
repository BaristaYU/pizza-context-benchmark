"""Batch model runs over kitchen orders with resume, attempt history and reports.

Ported from main's shared batch engine. The run identity, resume validation and
immutable attempt history (``batch.py``), the summary and HTML report
(``batch_report.py``) and the 429 stop behaviour are the same. This version drives the
coordinate kitchen through ``ai_runner.run_agent`` and adds a total cost budget.
"""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from threading import Event

from . import ai_runner
from .batch import prepare_run, store_attempt, write_json
from .batch_report import render_html, summarize
from .controls import build_controls
from .game_cli import ToolEnvironment
from .kitchen import VERSION as KITCHEN_VERSION
from .providers import RequestPacer, create_session


RETRYABLE = {"api_error", "not_run", "cancelled", "time_limit", "request_limit", "tool_limit", "cost_limit"}


def preflight_cases(cases, **environment_options):
    """Every case must open in the kitchen before any model request is sent."""
    failures = []
    for case in cases:
        try:
            ToolEnvironment(case, **environment_options).ready()
        except Exception as exc:  # report every failing case together
            failures.append(f"{case.get('id')}: {exc}")
    if failures:
        raise ValueError("주방에서 열 수 없는 문항이 있습니다: " + "; ".join(failures[:5]))


def run_batch(cases, provider, model, key, folder, *, resume=False, request_interval=3, max_requests=60,
              max_tools=150, max_seconds=900, max_consecutive_errors=5, max_cost_usd=None,
              max_total_cost_usd=None, rules=None, session_options=None,
              environment_options=None, stop=None, on_event=None, session_factory=create_session,
              agent_runner=ai_runner.run_agent, config=None):
    environment_options = environment_options or {}
    session_options = session_options or {}
    config = config or ai_runner.load_config()
    preflight_cases(cases, **environment_options)
    if not key and provider != "vllm":
        raise ValueError("선택 서비스의 API 키를 설정하세요.")
    if (max_cost_usd is not None or max_total_cost_usd is not None) and not ai_runner.model_price(provider, model, config):
        raise ValueError(f"{model}의 단가가 configs/agent_models.json에 없어 비용 한도를 적용할 수 없습니다.")
    folder = Path(folder)
    stop = stop or Event()
    pacer = RequestPacer(request_interval)
    # Building a client only reads its settings; it sends no model request.
    probe = session_factory(provider, key, model, pacer=pacer, stop=stop, **session_options)
    try:
        controls = build_controls(cases, getattr(probe, "settings", {}), rules=rules,
                                  request_interval=request_interval, max_requests=max_requests,
                                  max_tools=max_tools, max_seconds=max_seconds,
                                  max_consecutive_errors=max_consecutive_errors, max_cost_usd=max_cost_usd)
    finally:
        probe.close()
    manifest, reports = prepare_run(folder, cases, provider, model, resume, controls=controls)
    recovery = None
    state_path = folder / "batch_state.json"
    if resume and state_path.exists():
        old_state = json.loads(state_path.read_text(encoding="utf-8"))
        if old_state.get("status") == "running":
            recovery = {"previous_active_case_id": old_state.get("active_case_id"), "restart_policy": "initial_state",
                        "usage_note": "강제 종료 직전 요청의 사용량은 응답을 받지 못했으면 미확인입니다."}
            archive = {"state": old_state, "recovery": recovery}
            snapshot_path = folder / "active_case_snapshot.json"
            if snapshot_path.exists():
                archive["snapshot"] = json.loads(snapshot_path.read_text(encoding="utf-8"))
            target = folder / "history" / "recovery" / ("exit_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json")
            target.parent.mkdir(parents=True, exist_ok=True)
            write_json(target, archive)
    if resume and (folder / "summary.json").exists():
        backup = folder / "history" / "summaries" / ("summary_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json")
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes((folder / "summary.json").read_bytes())

    def sanitized(value):
        text = json.dumps(value, ensure_ascii=False)
        return json.loads(text.replace(key, "[REDACTED]") if key else text)

    def emit(event):
        if on_event:
            on_event(sanitized(event))

    batch_stop = None
    operational_warnings = []
    spent = 0.0  # this invocation only; earlier attempts are already paid and stay in the history

    def journal(status, active_case_id=None):
        write_json(state_path, {"status": status, "active_case_id": active_case_id,
                                "updated_at": datetime.now().astimezone().isoformat(),
                                "restart_policy": "initial_state"})

    def persist():
        summary = summarize(cases, reports, model)
        summary.update(provider=provider, dataset_fingerprint=manifest["dataset_fingerprint"],
                       control_fingerprint=manifest["control_fingerprint"],
                       service_fingerprint=manifest.get("service_fingerprint"), controls=manifest["controls"],
                       run_manifest=manifest, batch_stop_reason=batch_stop, recovery=recovery,
                       operational_warnings=operational_warnings, environment=KITCHEN_VERSION,
                       batch_cost_limit_usd=max_total_cost_usd, batch_spent_usd=round(spent, 6),
                       usage_measurement={"policy": "Observation only; prompts, tools, kitchen, grading and API parameters are unchanged.",
                                          "request_counts": "Request attempts reported by the runner; usage only when returned by the provider."})
        write_json(folder / "summary.json", summary)
        (folder / "report.html").write_text(render_html(summary), encoding="utf-8")
        return summary

    summary = persist()
    journal("running")
    emit({"kind": "batch_ready", "folder": str(folder), "summary": summary})
    for index, case in enumerate(cases):
        if stop.is_set():
            batch_stop = "cancelled"
            break
        previous = reports[index]
        if previous["termination"] not in RETRYABLE:
            emit({"kind": "batch_progress", "index": index + 1, "total": len(cases), "case_id": case["id"],
                  "preserved": True, "report": previous, "summary": summary})
            continue
        case_limit = max_cost_usd
        if max_total_cost_usd is not None:
            remaining = max_total_cost_usd - spent
            if remaining <= 0:
                batch_stop = "cost_limit"
                break
            case_limit = remaining if case_limit is None else min(case_limit, remaining)
        journal("running", case["id"])
        write_json(folder / "active_case_snapshot.json",
                   {"case_id": case["id"], "status": "starting", "request_usage": "not yet observed"})

        def checkpoint(event, case_id=case["id"]):
            snapshot = sanitized({"case_id": case_id, "status": "in_progress",
                                  "updated_at": datetime.now().astimezone().isoformat(),
                                  "requests": event.get("requests"), "records": event.get("records", [])})
            try:
                write_json(folder / "active_case_snapshot.json", snapshot)
            except OSError:
                operational_warnings.append("진행 기록을 저장하지 못해 후속 실행을 중지했습니다.")
                stop.set()
            emit({"kind": "batch_case_progress", "case_id": case_id, "requests": event.get("requests")})

        emit({"kind": "batch_case_start", "case_id": case["id"], "index": index + 1, "total": len(cases)})
        session = None
        try:
            session = session_factory(provider, key, model, pacer=pacer, stop=stop, **session_options)
            report = agent_runner(case, session, stop=stop, rules=rules,
                                  max_requests=max_requests, max_tools=max_tools, max_seconds=max_seconds,
                                  max_consecutive_errors=max_consecutive_errors, max_cost_usd=case_limit,
                                  on_event=checkpoint, config=config, **environment_options)
        except KeyboardInterrupt:
            stop.set()
            batch_stop = "cancelled"
            break
        except Exception as exc:
            code = getattr(exc, "code", None)
            report = {"case_id": case["id"], "model": model,
                      "termination": "cancelled" if stop.is_set() else "api_error", "requests": 0,
                      "error": None if stop.is_set() else ai_runner.safe_error(exc),
                      "error_code": code if isinstance(code, int) and not stop.is_set() else None}
        finally:
            if session:
                session.close()
        report["provider"] = provider
        spent += (report.get("cost") or {}).get("total_usd") or 0
        write_json(folder / "active_case_snapshot.json",
                   sanitized({"case_id": case["id"], "status": "result_received", "report": report}))
        reports[index] = store_attempt(folder, sanitized(report), previous)
        journal("running")
        if report.get("error_code") == 429:
            batch_stop = "quota"
        elif stop.is_set():
            batch_stop = "cancelled"
        elif max_total_cost_usd is not None and spent >= max_total_cost_usd:
            batch_stop = "cost_limit"
        summary = persist()
        emit({"kind": "batch_progress", "index": index + 1, "total": len(cases), "case_id": case["id"],
              "preserved": False, "report": reports[index], "summary": summary})
        if batch_stop:
            break
    journal(batch_stop or "finished")
    summary = persist()
    result = {"folder": str(folder), "summary": summary, "reports": deepcopy(reports)}
    emit({"kind": "batch_done", **result})
    return result
