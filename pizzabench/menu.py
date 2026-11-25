"""The shop's menu board: what each named pizza holds and which toppings a category covers.

Customers order by recipe name ("a Hawaiian") or by category ("all the stinky toppings").
A cook in the shop can read the menu board, so every client gets the same menu: models in
the ready event and in the Reasoning and E2E inputs, people through the menu window.
"""

from copy import deepcopy
import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "menu.json"
_MENU = json.loads(PATH.read_text(encoding="utf-8"))
VERSION = _MENU["version"]


def menu():
    return deepcopy(_MENU)


def readable():
    """The menu as short lines for people."""
    lines = ["이름 붙은 피자"]
    for name, recipe in _MENU["recipes"].items():
        sauce = {"any": "소스(토마토나 페스토)", "tomato": "토마토 소스", "pesto": "페스토 소스", "none": "소스 없음"}[recipe["sauce"]]
        base = [sauce] + (["치즈"] if recipe["cheese"] else [])
        lines.append(f"- {name}: " + ", ".join(base + recipe["toppings"]))
    lines += ["", "토핑 범주"]
    lines += [f"- {name}: " + ", ".join(items) for name, items in _MENU["categories"].items()]
    return "\n".join(lines)
