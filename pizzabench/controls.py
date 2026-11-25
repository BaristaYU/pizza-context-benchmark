"""Experiment identity for kitchen model runs. Never rewrites prompts, tools or API parameters.

Two fingerprints are kept apart:

* ``fingerprint`` covers what every compared run must share: the prompt format, rules,
  tool definitions, kitchen and grading code, data and budgets.
* ``service_fingerprint`` covers how one service is called: API, transport, output
  limits and other generation settings. A resumed run must keep both. Runs on different
  services can be compared when the first matches, and the comparison report lists the
  service settings that differ instead of treating them as equal.
"""

import hashlib
import json
from pathlib import Path

from .ai_runner import PROMPT_FORMAT
from .batch import dataset_fingerprint
from .game_cli import PROTOCOL_VERSION, tool_definitions
from .kitchen import Kitchen


ROOT = Path(__file__).resolve().parent.parent
CONTROLLED_FILES = ("pizzabench/ai_runner.py", "pizzabench/kitchen.py", "pizzabench/game.py",
                    "pizzabench/grading.py", "pizzabench/execution_eval.py",
                    "docs/pizza_domain_rules.md", "data/menu.json")
SERVICE_FILES = ("pizzabench/providers.py",)
OPERATIONAL_SETTINGS = {"provider", "model", "request_interval_seconds", "request_timeout_ms", "retry_attempts",
                        "transport"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def source_digest(path):
    """Hash text independent of a byte-order mark and CRLF/LF checkouts."""
    text = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_controls(cases, settings, *, rules=None, request_interval=3, max_requests=60,
                   max_tools=150, max_seconds=900, max_consecutive_errors=5, max_cost_usd=None):
    experiment = {"version": 1,
                  "source_files": {name: source_digest(ROOT / name) for name in CONTROLLED_FILES},
                  "prompt_format": PROMPT_FORMAT,
                  "rules_sha256": hashlib.sha256(rules.encode("utf-8")).hexdigest() if rules else None,
                  "tool_definitions_sha256": digest(tool_definitions(Kitchen())),
                  "protocol_version": PROTOCOL_VERSION,
                  "dataset_fingerprint": dataset_fingerprint(cases),
                  "limits": {"requests": max_requests, "tools": max_tools, "seconds": max_seconds,
                             "consecutive_errors": max_consecutive_errors, "cost_usd": max_cost_usd}}
    # Operational values are recorded but do not change what the model is asked to do.
    generation = {key: value for key, value in settings.items() if key not in OPERATIONAL_SETTINGS}
    service = {"version": 1, "provider": settings.get("provider"),
               "source_files": {name: source_digest(ROOT / name) for name in SERVICE_FILES},
               "generation_settings": generation,
               "operational_settings": {key: settings.get(key) for key in sorted(OPERATIONAL_SETTINGS - {"model"})
                                        if key in settings} | {"request_interval_seconds": float(request_interval)}}
    return {**experiment, "fingerprint": digest(experiment),
            "service": service, "service_fingerprint": digest(service)}
