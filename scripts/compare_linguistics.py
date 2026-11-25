"""Compare the assistant's L draft with the annotators' order forms.

    python scripts/compare_linguistics.py data/english100/l_annotations/L_결과_*.json --output l_review.md

The annotators split the 100 cases, so each case is compared once: draft against the
annotator who answered it. The report gives exact agreement per stage, the options that
differ most, every differing case with its options, so the team can settle the ground
truth, and the understanding-difficulty labels before and after the clarification.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from pizzabench.linguistics_form import STAGES, compare, ticked  # noqa: E402

DATA = REPO / "data" / "english100" / "benchmark_cases.jsonl"


def load_draft(path=DATA):
    forms, texts = {}, {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            case = json.loads(line)
            texts[case["id"]] = case["question"]["order_text"]
            for stage in STAGES:
                forms[(case["id"], stage)] = case["linguistics"][stage]
    return forms, texts


def load_annotations(path):
    """Finished answers from a tool result file: forms per (case, stage) and difficulty per (case, stage).

    Drafts are work in progress and are left out."""
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    forms, difficulty = {}, {}
    for case_id, answer in value["answers"].items():
        labels = answer.get("difficulty") or {}
        for stage in STAGES:
            forms[(case_id, stage)] = answer[stage]
            difficulty[(case_id, stage)] = labels.get(stage)
    return value.get("annotator") or Path(path).stem, forms, difficulty


def option_of(difference):
    """'pizza 1 side 2: olive expected True, got False' -> 'olive'."""
    match = re.search(r"([a-z_0-9]+):? expected", difference)
    return match.group(1) if match else difference


def pair(name_a, forms_a, name_b, forms_b):
    shared = sorted(set(forms_a) & set(forms_b))
    rows, options = [], Counter()
    for key in shared:
        result = compare(forms_a[key], forms_b[key])
        if not result["passed"]:
            rows.append((key, result))
            options.update(option_of(difference) for difference in result["differences"])
    by_stage = {stage: [k for k in shared if k[1] == stage] for stage in STAGES}
    return {"a": name_a, "b": name_b, "shared": len(shared), "disagreements": rows, "options": options,
            "agreement": {stage: (len(keys) - sum(1 for k, _ in rows if k[1] == stage), len(keys))
                          for stage, keys in by_stage.items()}}


def render(results, draft, texts):
    lines = ["# L 주문서 일치도", ""]
    for result in results:
        lines.append(f"## {result['a']} 대 {result['b']}")
        lines.append("")
        for stage, (same, total) in result["agreement"].items():
            rate = f"{same / total * 100:.1f}%" if total else "비교할 답 없음"
            lines.append(f"- {stage}: {same} / {total} 일치 ({rate})")
        if result["options"]:
            lines.append("- 가장 자주 갈린 선택지: " + ", ".join(f"{k} {v}회" for k, v in result["options"].most_common(10)))
        lines.append("")
        for (case_id, stage), outcome in result["disagreements"]:
            lines.append(f"### {case_id} · {stage}")
            lines.append(f"주문: {texts.get(case_id, '')}")
            lines.append("")
            if outcome.get("form_error"):
                lines.append(f"- 형식 오류: {outcome['form_error']}")
            lines += [f"- {difference}" for difference in outcome["differences"]]
            lines.append(f"- {result['a']}: " + "; ".join(ticked(draft[result['a']][(case_id, stage)])))
            lines.append("")
    return "\n".join(lines)


LEVELS = ("하", "중", "상")


def merged_labels(difficulties):
    labels = {}
    for per_annotator in difficulties.values():
        labels.update({key: value for key, value in per_annotator.items() if value})
    return labels


def write_difficulty(difficulties, data_path=DATA):
    """Store the understanding-difficulty labels in the cases (question.difficulty.lcs) and rebuild."""
    from pizzabench.data_io import read_jsonl, write_jsonl
    from pizzabench.english100 import rebuild
    labels = merged_labels(difficulties)
    rows = read_jsonl(data_path)
    for row in rows:
        lcs = row["question"]["difficulty"].setdefault("lcs", {"initial": None, "clarified": None})
        for stage in STAGES:
            if (row["id"], stage) in labels:
                lcs[stage] = labels[(row["id"], stage)]
    write_jsonl(data_path, rows)
    rebuild(Path(data_path).parent)
    return sum(bool(r["question"]["difficulty"]["lcs"]["initial"]) for r in rows)


def render_balance(labels, data_path=DATA):
    """Structure tier against first-utterance understanding, to see which cells need rebalancing."""
    tiers = {}
    for line in Path(data_path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            case = json.loads(line)
            tiers[case["id"]] = case["question"]["difficulty"]["ocs"]
    cells = Counter((tiers[c], labels[(c, "initial")]) for c, s in labels if s == "initial" and c in tiers)
    lines = ["", "## 구조 난이도 대 이해 난이도(① 첫 말)", "",
             "| 구조 \\ 이해 | " + " | ".join(LEVELS) + " | 합 |", "| --- |" + " --- |" * (len(LEVELS) + 1)]
    for tier in LEVELS:
        row = [cells.get((tier, level), 0) for level in LEVELS]
        lines.append(f"| {tier} | " + " | ".join(map(str, row)) + f" | {sum(row)} |")
    totals = [sum(cells.get((tier, level), 0) for tier in LEVELS) for level in LEVELS]
    lines.append("| 합 | " + " | ".join(map(str, totals)) + f" | {sum(totals)} |")
    return "\n".join(lines)


def render_difficulty(difficulties):
    """Label counts per stage, and how labels move from the first utterance to after the clarification."""
    labels = merged_labels(difficulties)
    cases = sorted({case_id for case_id, _ in labels})
    lines = ["# 이해 난이도 라벨", ""]
    for stage, title in (("initial", "① 첫 말"), ("clarified", "② 다시 들은 뒤")):
        counts = Counter(labels[(case_id, stage)] for case_id in cases)
        lines.append(f"- {title}: " + ", ".join(f"{level} {counts.get(level, 0)}개" for level in LEVELS))
    moves = Counter((labels[(c, "initial")], labels[(c, "clarified")]) for c in cases)
    lines += ["", "| ① \\ ② | " + " | ".join(LEVELS) + " |", "| --- |" + " --- |" * len(LEVELS)]
    for before in LEVELS:
        lines.append(f"| {before} | " + " | ".join(str(moves.get((before, after), 0)) for after in LEVELS) + " |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("annotations", nargs="+", type=Path, help="Result files from the annotation tool")
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, help="Markdown report path")
    parser.add_argument("--write-difficulty", action="store_true",
                        help="Store the understanding-difficulty labels in the data and rebuild it")
    options = parser.parse_args(argv)
    draft_forms, texts = load_draft(options.data)
    sources, difficulties = {"draft": draft_forms}, {}
    for path in options.annotations:
        name, forms, difficulty = load_annotations(path)
        sources[name], difficulties[name] = forms, difficulty
    results = [pair("draft", draft_forms, name, forms) for name, forms in sources.items() if name != "draft"]
    report = (render(results, sources, texts) + "\n" + render_difficulty(difficulties)
              + render_balance(merged_labels(difficulties), options.data))
    if options.output:
        options.output.write_text(report + "\n", encoding="utf-8")
    for result in results:
        summary = ", ".join(f"{stage} {same}/{total}" for stage, (same, total) in result["agreement"].items())
        print(f"{result['a']} vs {result['b']}: {summary}")
    if options.write_difficulty:
        print(f"Stored understanding difficulty for {write_difficulty(difficulties, options.data)} cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
