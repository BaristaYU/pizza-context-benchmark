"""Independent evaluation of a model's A given the completed L and menu."""

import json

from . import l_to_a, linguistics_form, structured_eval
from .task_inputs import build_task_input


INPUT_STAGE = "clarified"
PROMPT_FORMAT = "reasoning-l-menu-v1"
SCORING_VERSION = "reasoning-a-v1"
SAUCES = ("any", "tomato", "pesto")
REGIONS = ("whole", "left", "right")

INSTRUCTIONS = """Derive the final requirements A from the completed order form (linguistics) and menu.
Return one JSON object with pizza_count and pizzas, or an object with an alternatives array
of complete orders when multiple distinct orders are allowed. Include every required pizza.

For each side, start with sauce of any kind and cheese. Expand checked recipe_* and category_*
options with the menu, including a recipe or category's sauce and cheese if specified.
Add checked ingredients and apply the no_* exclusions and the explicit sauce and cheese
choices. Treat cheese as a layer. The topping key sliced_tomato means tomato. A single
side applies to the whole pizza.

Each pizza lists sauce (an array of any, tomato or pesto), cheese (a boolean), and toppings
(an array of ingredient IDs). Use empty arrays for no sauce or no toppings. Include a
topping_placement object mapping every topping to whole, left or right. Use sauce_placement
when sauce is present and cheese_placement when cheese is present. Use consistent left/right
coordinates across ingredients. Include allow_half_swap: true if the two sides have different
requirements. If one half requires a particular sauce and the other accepts either, enumerate
the complete orders for both choices.

Include dough: wheat for wheat_dough, bake: well_done for bake_twice, and cuts for a checked
slice option (0 for no_cut). Omit dough, bake and cuts when the corresponding options are unset.
Keep sauce as ["any"] when the kind is free across its required area. Preserve the order's
requirements and leave unconstrained attributes out."""


class AnswerFormatError(ValueError):
    """The response cannot be scored as a structured Answer."""


def _nonnegative_int(value):
    return type(value) is int and value >= 0


def _names(value):
    return (isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)
            and len(set(value)) == len(value))


def _sauces(value):
    return (_names(value) and all(item in SAUCES for item in value)
            and ("any" not in value or len(value) == 1))


def _mapping(value, valid):
    return (isinstance(value, dict)
            and all(isinstance(key, str) and key.strip() and valid(item) for key, item in value.items()))


def _quantity(value, *, halves=False):
    if _nonnegative_int(value):
        return True
    if not value or not _mapping(value, _nonnegative_int):
        return False
    if value.keys() <= {"min", "max"}:
        return value.get("min", 0) <= value.get("max", float("inf"))
    return halves and value.keys() <= {"left", "right"}


PIZZA_FIELDS = {
    "dough": lambda value: value in ("regular", "wheat"),
    "sauce": _sauces,
    "sauce_placement": lambda value: _mapping(value, lambda region: region in REGIONS),
    "cheese": lambda value: type(value) is bool,
    "cheese_placement": lambda value: value in REGIONS,
    "toppings": _names,
    "topping_placement": lambda value: _mapping(value, lambda region: region in REGIONS),
    "topping_counts": lambda value: _mapping(value, lambda count: _quantity(count, halves=True)),
    "topping_count": _quantity,
    "bake": lambda value: value in ("normal", "well_done"),
    "cuts": _nonnegative_int,
    "allow_half_swap": lambda value: type(value) is bool,
}


def _validate_order(order, path):
    if not isinstance(order, dict) or order.keys() != {"pizza_count", "pizzas"}:
        raise AnswerFormatError(f"{path} must have exactly pizza_count and pizzas")
    count, pizzas = order["pizza_count"], order["pizzas"]
    if type(count) is not int or count < 1:
        raise AnswerFormatError(f"{path}.pizza_count must be a positive integer")
    if not isinstance(pizzas, list):
        raise AnswerFormatError(f"{path}.pizzas must be an array")
    if count != len(pizzas):
        raise AnswerFormatError(f"{path}.pizza_count does not match the length of pizzas")
    for index, pizza in enumerate(pizzas):
        prefix = f"{path}.pizzas[{index}]"
        if not isinstance(pizza, dict):
            raise AnswerFormatError(f"{prefix} must be an object")
        for field, value in pizza.items():
            if field not in PIZZA_FIELDS:
                raise AnswerFormatError(f"{prefix}.{field} is not a supported field")
            if not PIZZA_FIELDS[field](value):
                raise AnswerFormatError(f"{prefix}.{field} has an invalid value")


def validate_answer(answer):
    if isinstance(answer, dict) and "alternatives" in answer:
        alternatives = answer["alternatives"]
        if answer.keys() != {"alternatives"} or not isinstance(alternatives, list) or not alternatives:
            raise AnswerFormatError("A must contain only a nonempty alternatives array")
        for index, order in enumerate(alternatives):
            _validate_order(order, f"A.alternatives[{index}]")
    else:
        _validate_order(answer, "A")
    return answer


def parse_answer(text):
    try:
        answer = structured_eval.parse_response(text)
    except ValueError as exc:
        raise AnswerFormatError(str(exc)) from exc
    return validate_answer(answer)


def build_prompt(case):
    inputs = build_task_input(case, "Reasoning", clarified=True)
    recipe_keys = json.dumps(linguistics_form.RECIPES, ensure_ascii=False)
    return f"{INSTRUCTIONS}\n\nRecipe keys: {recipe_keys}\n\n{json.dumps(inputs, ensure_ascii=False)}"


def preflight_cases(cases):
    for case in cases:
        try:
            if not isinstance(case.get("linguistics"), dict):
                raise ValueError("linguistics must be an object")
            inputs = build_task_input(case, "Reasoning", clarified=True)
            linguistics_form.validate(inputs["linguistics"])
            validate_answer(case["answer"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{case.get('id')}: Reasoning requires a valid clarified L and reference A ({exc})") from exc


def score_response(expected, text, *, actions=()):
    try:
        if actions:
            raise AnswerFormatError("The model returned a tool call instead of a JSON-only answer")
        answer = parse_answer(text)
    except AnswerFormatError as exc:
        return None, structured_eval.format_error(exc)
    passed = l_to_a.same_answer(expected, answer)
    return answer, {"status": "passed" if passed else "condition_mismatch", "passed": passed,
                    "errors": [] if passed else ["The returned A has different requirements"],
                    "differences": {} if passed else l_to_a.condition_differences(expected, answer)}


def run_case(case, session, **options):
    def assess(case, text, *, actions):
        answer, score = score_response(case["answer"], text, actions=actions)
        return {"normalized_answer": answer, "score": score}

    return structured_eval.run_case(case, session, task="Reasoning", scoring_version=SCORING_VERSION,
                                    input_stage=INPUT_STAGE, prompt_for=build_prompt, assess=assess, **options)


def estimate_cost(cases, provider, model, config=None):
    preflight_cases(cases)
    return structured_eval.estimate_cost(cases, provider, model, config, task="Reasoning",
                                         prompt_for=build_prompt, reference_for=lambda case: case["answer"])
