"""Select the permitted model inputs from a complete benchmark case."""

from copy import deepcopy

from .menu import menu


TASKS = {"NLU", "Reasoning", "Planning", "Tool Use", "Computer Use", "E2E"}


def build_task_input(case, task, *, clarified=False):
    """Return a task's model input without its reference output."""
    if task not in TASKS:
        raise ValueError(f"Unsupported task: {task}")
    if type(clarified) is not bool:
        raise ValueError("clarified must be a boolean")
    reads_question = task in {"NLU", "E2E"}
    if clarified and not reads_question and task != "Reasoning":
        raise ValueError(f"Clarification is not an input to {task}")

    result = {}
    if reads_question:
        question = case["question"]
        visible = {"order_text": question["order_text"]}
        if clarified:
            text = question.get("clarification_text")
            if text is None:
                raise ValueError("No clarification is available")
            visible["clarification_text"] = text
        result["question"] = visible
    if task in {"Reasoning", "E2E"}:
        # Recipe names and categories in an order are resolved with the shop's menu.
        result["menu"] = menu()

    if task == "Reasoning":
        key = "clarified" if clarified else "initial"
        analysis = case["linguistics"].get(key)
        if analysis is None:
            raise ValueError(f"No reference linguistic analysis for {key}")
        result["linguistics"] = analysis
    elif task == "Planning":
        result["answer"] = case["answer"]
    elif task in {"Tool Use", "Computer Use"}:
        result["tool_calling"] = case["tool_calling"]

    if task in {"Planning", "Tool Use", "Computer Use", "E2E"}:
        result["state"] = case["state"]
    return deepcopy(result)
