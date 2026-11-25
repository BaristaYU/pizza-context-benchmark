"""Order outcomes and concrete-plan execution are separate measurements."""

from copy import deepcopy
import math

from .grading import evaluate


OBSERVATION_TOOLS = {"observe"}


def validate_plan(plan):
    if not isinstance(plan, list):
        raise ValueError("Reference plan must be an array")
    for index, action in enumerate(plan):
        if (not isinstance(action, dict) or set(action) != {"tool", "args"}
                or not isinstance(action["tool"], str) or not isinstance(action["args"], dict)):
            raise ValueError(f"Reference action {index + 1} requires tool and args")
    return plan


def _equal(expected, actual):
    if type(expected) in (int, float) and type(actual) in (int, float):
        return math.isclose(expected, actual, rel_tol=0, abs_tol=1e-6)
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, dict):
        return expected.keys() == actual.keys() and all(_equal(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return len(expected) == len(actual) and all(_equal(a, b) for a, b in zip(expected, actual))
    return expected == actual


def plan_adherence(reference_plan, trace):
    """Compare successful production calls; observations/waits and retries may vary."""
    validate_plan(reference_plan)
    wanted = [deepcopy(a) for a in reference_plan if a["tool"] not in OBSERVATION_TOOLS]
    actual = [{"tool": r["tool"], "args": deepcopy(r["args"])} for r in trace
              if r.get("ok") is True and r["tool"] not in OBSERVATION_TOOLS]
    # LCS preserves order and identifies missing and extra production actions.
    lengths = [[0] * (len(actual) + 1) for _ in range(len(wanted) + 1)]
    for i in range(len(wanted) - 1, -1, -1):
        for j in range(len(actual) - 1, -1, -1):
            lengths[i][j] = (1 + lengths[i + 1][j + 1] if _equal(wanted[i], actual[j]) else
                             max(lengths[i + 1][j], lengths[i][j + 1]))
    missing, unexpected = [], []
    i = j = 0
    while i < len(wanted) and j < len(actual):
        if _equal(wanted[i], actual[j]):
            i, j = i + 1, j + 1
        elif lengths[i + 1][j] >= lengths[i][j + 1]:
            missing.append({"step": i + 1, **wanted[i]})
            i += 1
        else:
            unexpected.append({"step": j + 1, **actual[j]})
            j += 1
    missing.extend({"step": k + 1, **wanted[k]} for k in range(i, len(wanted)))
    unexpected.extend({"step": k + 1, **actual[k]} for k in range(j, len(actual)))
    return {"passed": not missing and not unexpected,
            "required_actions": len(wanted), "observed_actions": len(actual),
            "matched_actions": lengths[0][0], "missing_actions": missing, "unexpected_actions": unexpected,
            "ignored_tools": sorted(OBSERVATION_TOOLS)}


def assess_execution(answer, execution, *, reference_plan=None):
    """A success bit, plan adherence when requested, and unweighted diagnostics."""
    outcome = evaluate(answer, execution)
    trace = execution["trace"]
    plan = None if reference_plan is None else plan_adherence(reference_plan, trace)
    return {
        "passed": outcome["passed"] and (plan is None or plan["passed"]),
        "outcome": outcome, "plan": plan,
        "metrics": {
            "tool_calls": len(trace),
            "successful_calls": sum(r.get("ok") is True for r in trace),
            "failed_calls": sum(r.get("ok") is False for r in trace),
            "production_calls": sum(r["tool"] not in OBSERVATION_TOOLS | {"clarify"} for r in trace),
            "clarification_requests": sum(r["tool"] == "clarify" and r.get("ok") is True for r in trace),
            "simulation_seconds": execution["final_state"].get("time", 0),
        },
    }
