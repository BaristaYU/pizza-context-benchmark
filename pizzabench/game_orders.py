"""Small practice menu plus the existing, separately authored benchmark cases."""

from copy import deepcopy
import json
from pathlib import Path


PRACTICE = [
    {
        "id": "practice_olive", "label": "연습 · 올리브 피자",
        "question": {"order_text": "올리브 피자 한 판 주세요. 여섯 조각으로 잘라 주세요.",
                     "clarification_text": "소스와 치즈, 올리브가 올라간 피자요. 6조각으로 부탁해요."},
        "answer": {"pizza_count": 1, "pizzas": [{"sauce": ["any"], "cheese": True,
                    "toppings": ["olive"], "cuts": 6}]},
    },
    {
        "id": "practice_halves", "label": "연습 · 페퍼로니 / 버섯 반반",
        "question": {"order_text": "반은 페퍼로니, 나머지 반은 버섯으로 주세요. 소스와 치즈는 전체에요.",
                     "clarification_text": "페퍼로니와 버섯을 서로 다른 반쪽에 올려 주세요. 어느 쪽이든 괜찮아요."},
        "answer": {"pizza_count": 1, "pizzas": [{"sauce": ["any"], "cheese": True,
                    "sauce_placement": {"any": "whole"}, "cheese_placement": "whole",
                    "toppings": ["pepperoni", "mushroom"],
                    "topping_placement": {"pepperoni": "left", "mushroom": "right"}, "allow_half_swap": True}]},
    },
    {
        "id": "practice_well_done", "label": "연습 · 두 번 구운 치즈 피자",
        "question": {"order_text": "치즈 피자를 두 번 구워 주세요. 네 조각으로요.",
                     "clarification_text": "소스와 치즈만 올려서 오븐에 두 번, 그리고 4조각으로 잘라 주세요."},
        "answer": {"pizza_count": 1, "pizzas": [{"sauce": ["any"], "cheese": True,
                    "toppings": [], "bake": "well_done", "cuts": 4}]},
    },
    {
        "id": "practice_two", "label": "연습 · 피자 두 판",
        "question": {"order_text": "치즈 피자 한 판, 페퍼로니 피자 한 판 부탁해요.",
                     "clarification_text": "두 판 모두 소스와 치즈를 올리고, 한 판에만 페퍼로니를 넣어 주세요."},
        "answer": {"pizza_count": 2, "pizzas": [
            {"sauce": ["any"], "cheese": True, "toppings": []},
            {"sauce": ["any"], "cheese": True, "toppings": ["pepperoni"]}]},
    },
]


def load_orders(path=None):
    orders = deepcopy(PRACTICE)
    path = Path(path) if path else Path(__file__).resolve().parents[1] / "data/english100/benchmark_cases.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                case = json.loads(line)
                order = {"id": case["id"], "label": case["id"].rsplit("_", 1)[-1],
                         "question": case["question"], "answer": case["answer"]}
                if "state" in case and case["state"].get("environment_version", "").startswith("mock-kitchen-"):
                    order["state"] = case["state"]
                if "environment_version" in case and case["environment_version"].startswith("mock-kitchen-"):
                    if "state" not in order:
                        raise ValueError(f"Missing kitchen state: {case['id']}")
                orders.append(order)
    elif path is not None:
        raise ValueError(f"Order file not found: {path}")
    return orders
