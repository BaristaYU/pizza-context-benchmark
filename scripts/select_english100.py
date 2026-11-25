"""Draw the English 100 from the wiki data and write its authored fields, then rebuild the rest.

    python scripts/select_english100.py

Writes ``data/english100/benchmark_cases.jsonl`` (question, source, answer, review per case)
and ``data/english100/selection.json`` (pool counts, quotas, exclusions and the reserve
orders of each tier), then runs the English 100 rebuild. Case numbers follow a round-robin
over the tiers, so cases 1-50 and 51-100 hold each tier almost equally.

Annotator labels already merged into the data (question.difficulty.lcs, review) are kept
for orders that stay in the selection, and so are their case numbers. To rebalance, drop a
case; the next reserve order of the same tier takes its number:

    python scripts/select_english100.py --drop 12:0 --reason "too easy to understand"
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from pizzabench import english100_selection as selection, wiki_orders  # noqa: E402
from pizzabench.data_io import read_jsonl, write_jsonl  # noqa: E402
from pizzabench.english100 import DATA, difficulty_record, rebuild, write_json  # noqa: E402
from pizzabench.english100_linguistics import DRAFTS  # noqa: E402

REVIEW = {"status": "draft", "linguistics_status": "draft", "answer_status": "draft", "execution_status": "draft",
          "reviewer": "", "notes": "", "flags": []}


def reserve_view(item):
    return {"wiki_key": item["key"], "ocs": item["ocs"], "recipe": item["recipe"], "order_text": item["order_text"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DATA)
    parser.add_argument("--drop", nargs="*", default=[], help="wiki keys (entry:order) to replace")
    parser.add_argument("--reason", default="", help="why the dropped cases are replaced")
    options = parser.parse_args(argv)
    data = wiki_orders.load()
    record_path = options.output / "selection.json"
    dropped = json.loads(record_path.read_text(encoding="utf-8")).get("dropped", {}) if record_path.exists() else {}
    dropped.update({key: options.reason for key in options.drop})
    pool = list(selection.candidates(data))
    chosen, reserves = selection.select(pool, dropped=dropped)
    previous = {}
    target = options.output / "benchmark_cases.jsonl"
    if target.exists():
        previous = {row["source"]["wiki_key"]: row for row in read_jsonl(target) if "source" in row}
    ordered = selection.interleave(chosen)
    if previous:
        # Kept orders keep their case number; a replacement takes a number its tier freed.
        kept = {item["key"] for item in ordered}
        freed = {}
        for key, row in previous.items():
            if key not in kept:
                freed.setdefault(row["question"]["difficulty"]["ocs"], []).append(int(row["id"].rsplit("_", 1)[-1]))
        freed = {tier: sorted(ids) for tier, ids in freed.items()}
        numbers = {item["key"]: int(previous[item["key"]]["id"].rsplit("_", 1)[-1])
                   for item in ordered if item["key"] in previous}
        for item in ordered:
            if item["key"] not in numbers:
                numbers[item["key"]] = freed[item["ocs"]].pop(0)
    else:
        numbers = {item["key"]: position for position, item in enumerate(ordered, 1)}
    ordered.sort(key=lambda item: numbers[item["key"]])
    rows = []
    for item in ordered:
        number = numbers[item["key"]]
        old = previous.get(item["key"], {})
        question = {"language": "en", "order_text": item["order_text"], "clarification_text": item["clarification_text"],
                    "difficulty": difficulty_record(item["answer"], old.get("question", {}).get("difficulty"))}
        source = {"wiki_key": item["key"], "wiki_page": "List_of_orders",
                  "wiki_revision": data["source"]["pages"]["wiki/List_of_orders"],
                  "category": item["category"], "section": item["section"], "recipe": item["recipe"],
                  "note": item["note"], "cuts": item["cuts"], "bake": item["bake"]}
        rows.append({"id": f"en100_{number:03d}", "question": question, "source": source,
                     "answer": item["answer"], "review": old.get("review", dict(REVIEW))})
    write_jsonl(target, rows)
    pool_entries = {}
    for item in pool:
        if item["key"] not in selection.EXCLUDED:
            pool_entries.setdefault(item["ocs"], set()).add(item["entry"])
    write_json(options.output / "selection.json", {
        "seed": selection.SEED, "quotas": selection.QUOTAS,
        "pool": {"orders": dict(Counter(i["ocs"] for i in pool if i["key"] not in selection.EXCLUDED)),
                 "wiki_recipes": {t: len(v) for t, v in pool_entries.items()}},
        "rule": "One order per wiki recipe, taken in seeded shuffle order until each structure tier fills its quota. "
                "Reserves continue the same order and can replace a case of the same tier.",
        "excluded": selection.EXCLUDED,
        "dropped": dropped,
        "selected": [{"id": r["id"], "wiki_key": r["source"]["wiki_key"], "ocs": i["ocs"]}
                     for r, i in zip(rows, ordered)],
        "reserves": {t: [reserve_view(i) for i in items] for t, items in reserves.items()},
    })
    missing = [r["source"]["wiki_key"] for r in rows if r["source"]["wiki_key"] not in DRAFTS]
    if missing:
        print("Write L drafts in pizzabench/english100_linguistics.py for:", ", ".join(missing))
        print("then run python -m pizzabench.english100 to rebuild.")
        return 1
    cases = rebuild(options.output, progress=lambda n: print(f"\r{n}/{len(rows)}", end="", flush=True))
    print(f"\nSelected and rebuilt {len(cases)} cases: {dict(Counter(c['question']['difficulty']['ocs'] for c in cases))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
