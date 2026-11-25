"""English 100-item Q-SLATE set: executable references rebuilt from the stored Q, A and source.

``benchmark_cases.jsonl`` holds the authored part of each case: the question, the wiki
source it was taken from, the answer and the review record. ``scripts/select_english100.py``
writes them from the wiki data. ``rebuild`` derives everything else from them and from the
L drafts in ``english100_linguistics``: the initial state, the reference plan, its real
execution in the kitchen, the reference evaluation, the difficulty record and the task
input files. Running it twice gives the same files.
"""

from copy import deepcopy
import json
import math
from pathlib import Path

from .data_io import read_jsonl, write_jsonl
from .english100_linguistics import NOTES as REVIEW_NOTES, draft as linguistics_draft
from .game import run_plan
from .kitchen import GUIDE_POINTS, Kitchen, VERSION
from .structure_difficulty import ocs, tier
from .task_inputs import build_task_input


DATASET_VERSION = "english100-v3-draft"
DATA = Path(__file__).resolve().parents[1] / "data" / "english100"
# The 28 toppings of the wiki's current order list; event-only toppings in its archive are not stocked.
TOPPINGS = ("pepperoni", "sausage", "mushroom", "olive", "onion", "bell_pepper", "anchovy", "basil", "bacon",
            "ham", "pineapple", "shrimp", "corn", "chicken", "eggplant", "jalapeno", "garlic", "tomato",
            "avocado", "truffle", "fig", "zucchini", "artichoke", "pumpkin", "duck", "peach", "apple", "scallop")
AUTHORED_FIELDS = ("id", "question", "source", "answer", "review")
REFERENCE_DEFAULTS = {"dough": "regular", "sauce_if_any": "tomato", "bake": "normal", "cuts": 6,
                      "topping_pieces_whole": 16, "topping_pieces_half": 8}


def write_json(path, value):
    with Path(path).open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def make_initial_state():
    inventory = {"dough": {"regular": 100, "wheat": 100}, "sauce": {"tomato": 100, "pesto": 100},
                 "cheese": 100, "topping": {name: 100 for name in TOPPINGS}}
    return Kitchen(inventory=inventory, oven_seconds=6).snapshot()


def plan_from_answer(answer, state):
    """Choose one admissible composition; defaults here never strengthen A."""
    chosen = answer.get("alternatives", [answer])[0]
    plan = []

    def add(tool, **args):
        plan.append({"tool": tool, "args": args})
    for index, pizza in enumerate(chosen["pizzas"], state["next_pizza_id"]):
        add("create", dough=pizza.get("dough", "regular"))
        add("spread", pizza=index)
        for sauce in pizza["sauce"]:
            concrete = "tomato" if sauce == "any" else sauce
            add("fill", pizza=index, item="sauce", kind=concrete, region=pizza.get("sauce_placement", {}).get(sauce, "whole"))
        if pizza["cheese"]:
            add("fill", pizza=index, item="cheese", region=pizza.get("cheese_placement", "whole"))
        for kind in pizza["toppings"]:
            region = pizza.get("topping_placement", {}).get(kind, "whole")
            quantity = pizza.get("topping_counts", {}).get(kind, 16 if region == "whole" else 8)
            if isinstance(quantity, dict):
                if quantity.keys() <= {"min", "max"}:
                    quantity = max(quantity.get("min", 1), min(quantity.get("max", 16), 16))
                else:
                    raise ValueError("Reference planner needs integer or range quantities")
            if type(quantity) is not int or quantity < 1:
                raise ValueError("A required topping needs positive integer quantity")
            # The default count fills the guide grid of the region; other counts go on a circle.
            guides = [p for p in GUIDE_POINTS if region == "whole" or (p[0] < 0) == (region == "left")]
            if quantity == len(guides):
                points = guides
            else:
                base = math.pi / 2 if region == "left" else -math.pi / 2
                sweep = 2 * math.pi if region == "whole" else math.pi
                points = [(round(.6 * math.cos(base + (j + .5) * sweep / quantity), 6),
                           round(-.6 * math.sin(base + (j + .5) * sweep / quantity), 6)) for j in range(quantity)]
            add("place_toppings", pizza=index, kind=kind, points=[[x, y] for x, y in points])
        for _ in range(2 if pizza.get("bake") == "well_done" else 1):
            add("bake", pizza=index)
        slices = pizza.get("cuts", 6)
        if type(slices) is not int or slices < 0 or slices % 2:
            raise ValueError("The current cutter supports zero or even slice counts")
        for j in range(slices // 2):
            add("cut", pizza=index, angle=round(-90 + j * 360 / slices, 6))
        add("serve", pizza=index)
    return plan


def compact_execution(execution):
    """Retain actual calls and final physics; summarize repeated pizza responses."""
    value = deepcopy(execution)
    for entry in value["trace"]:
        response = entry.get("result")
        if isinstance(response, dict) and "pieces" in response and "id" in response:
            entry["result"] = {k: response[k] for k in ("id", "stage", "location")}
    return value


def complete_case(case):
    """Add the reference T and E to a case with Q, S, L and A, checking that E satisfies A."""
    value = deepcopy(case)
    value["tool_calling"] = plan_from_answer(value["answer"], value["state"])
    report = run_plan(value, value["tool_calling"])
    if not report["score"]["passed"] or any(not t["ok"] for t in report["execution"]["trace"]):
        raise ValueError(f"Reference execution failed: {value['id']}: {report['score']}")
    value["execution"] = compact_execution(report["execution"])
    value["reference_evaluation"] = report["evaluation"]
    return value


def difficulty_record(answer, previous=None):
    """Structure difficulty from A, and the understanding difficulty that annotators label.

    ``lcs`` keeps the labels for the first utterance and after the clarification; they stay
    null until the team's labels are merged."""
    score = ocs(answer)
    lcs = (previous or {}).get("lcs") or {"initial": None, "clarified": None}
    return {"ocs": tier(answer), "ocs_level": score["level"], "ocs_raw": score["raw"],
            "ocs_breakdown": score["breakdown"], "lcs": lcs}


def case_from_authored(row):
    key = row["source"]["wiki_key"]
    question = {k: row["question"][k] for k in ("language", "order_text", "clarification_text")}
    question["difficulty"] = difficulty_record(row["answer"], row["question"].get("difficulty"))
    review = deepcopy(row["review"])
    review["notes"] = REVIEW_NOTES.get(key, review.get("notes", ""))
    return complete_case({"id": row["id"], "environment_version": VERSION, "question": question,
                          "source": deepcopy(row["source"]), "state": make_initial_state(),
                          "linguistics": dict(zip(("initial", "clarified"), linguistics_draft(key))),
                          "answer": deepcopy(row["answer"]), "review": review})


def rebuild(output=DATA, progress=None):
    """Regenerate every derived file of the English 100 set from its authored fields."""
    output = Path(output)
    authored = [{key: row[key] for key in AUTHORED_FIELDS} for row in read_jsonl(output / "benchmark_cases.jsonl")]
    cases = []
    for row in authored:
        cases.append(case_from_authored(row))
        if progress is not None:
            progress(len(cases))
    write_jsonl(output / "benchmark_cases.jsonl", cases)
    write_jsonl(output / "questions.jsonl", [{"id": c["id"], **c["question"]} for c in cases])
    write_task_inputs(cases, output)
    validation = {"count": len(cases), "outcomes_passed": len(cases),
                  "reference_pizzas": sum(len(c["answer"].get("alternatives", [c["answer"]])[0]["pizzas"]) for c in cases),
                  "reference_actions": sum(len(c["tool_calling"]) for c in cases),
                  "cases": [{"id": c["id"], "outcome_passed": True, "actions": len(c["tool_calling"]),
                             "ocs": c["question"]["difficulty"]["ocs"]} for c in cases]}
    write_json(output / "validation.json", validation)
    manifest = {
        "dataset_version": DATASET_VERSION, "language": "en", "count": len(cases),
        "environment_version": VERSION, "reference_defaults": REFERENCE_DEFAULTS,
        "inventory": "Regular and wheat dough, tomato and pesto sauce, cheese and 28 toppings; 100 units of each.",
        "question_source": "Order and clarification lines from the Good Pizza, Great Pizza wiki (data/wiki); source.wiki_key locates each.",
        "answer_source": "A is the wiki recipe of the order (source.recipe), with slicing and double baking that the order asks for "
                         "(source.cuts, source.bake). The clarified L leads to the same A through data/menu.json.",
        "answer_policy": "Only requirements stated in the order or implied by a named recipe or category are imposed. "
                         "Unspecified cuts, bake, dough and exact topping counts are omitted from Answer. "
                         "Reference defaults apply to T/E only.",
        "execution_trace": "Actual call records with repeated pizza-shaped responses reduced to id/stage/location; "
                           "final_state preserves the full physical state.",
        "difficulty": "question.difficulty holds the order-structure tier computed from A (ocs) and the annotators' "
                      "understanding difficulty before and after the clarification (lcs, null until labelled). "
                      "The cases were drawn 33/33/34 by ocs tier; see selection.json for the pool and reserves.",
        "review_status": "draft", "approved_count": sum(c["review"]["status"] == "approved" for c in cases),
    }
    write_json(output / "manifest.json", manifest)
    return cases


def write_task_inputs(cases, output):
    directory = Path(output) / "inputs"
    directory.mkdir(parents=True, exist_ok=True)
    for name, task, clarified in (
        ("nlu_initial", "NLU", False), ("nlu_clarified", "NLU", True),
        ("reasoning_clarified", "Reasoning", True), ("planning", "Planning", False),
        ("tool_use", "Tool Use", False), ("e2e", "E2E", False),
    ):
        write_jsonl(directory / f"{name}.jsonl", [{"case_id": c["id"], "model_input": build_task_input(c, task, clarified=clarified)}
                                                 for c in cases])


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Rebuild the derived English 100 files from Q, L and A")
    parser.add_argument("--output", type=Path, default=DATA)
    options = parser.parse_args(argv)
    cases = rebuild(options.output, progress=lambda n: print(f"\r{n}/100", end="", flush=True))
    print(f"\nRebuilt {len(cases)} cases; every reference execution passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
