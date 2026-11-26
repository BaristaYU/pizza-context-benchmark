"""L as a fixed multiple-choice order form shared by every order.

L is the customer's order sheet, like a kiosk or delivery-app order with options
ticked. A is the cook's recipe made from that sheet. L therefore records what the
customer asks for in the form's own vocabulary: a named recipe stays a recipe, a
category stays a category, and turning them into ingredients is A's job.

Every order uses the same keys and every value is true or false. The order is a list
of pizza entries, one per pizza to make, so the number of pizzas is the number of
entries. A pizza has pizza-level options and one side, or two sides when it is
half-and-half. Each side answers the same side options with true or
false. Sauce and cheese are on by default, as on a kiosk; ``no_sauce`` and
``no_cheese`` remove them. A topping, category or recipe left false is not added.
The slice count and the sauce are single choices: at most one of their options is
true, and none means the default (six slices, any sauce).
Categories and named recipes are the ones on the menu (``data/menu.json``). Every
regular order on the wiki can be written on the form; ``tests/test_wiki_orders.py`` checks
this.
"""

from itertools import permutations


FORM_VERSION = "l-form-v3"

PIZZA_OPTIONS = {
    "wheat_dough": ("밀 도우", "Wheat dough instead of regular dough"),
    "bake_twice": ("두 번 굽기", "Baked twice: dark crust, well done, crispy, double-baked"),
    "slices_2": ("2조각", "Cut into 2 slices"),
    "slices_4": ("4조각", "Cut into 4 slices"),
    "slices_8": ("8조각", "Cut into 8 slices"),
    "slices_18": ("18조각", "Cut into 18 slices"),
    "no_cut": ("자르지 않기", "Leave the pizza uncut"),
    "half_and_half": ("반반", "The two halves differ; sides then holds two option sets"),
}

SAUCE_CHEESE = {
    "tomato_sauce": ("토마토", "Tomato (red) sauce is asked for"),
    "pesto_sauce": ("페스토", "Pesto (green) sauce is asked for"),
    "no_sauce": ("소스 빼기", "No sauce"),
    "no_cheese": ("치즈 빼기", "No cheese"),
}

# Options of which at most one is true; none true means the default.
SINGLE_CHOICES = (
    {"title": "도우", "default": "일반 도우(기본)", "keys": ("wheat_dough",)},
    {"title": "조각 수", "default": "6조각(기본)",
     "keys": ("slices_2", "slices_4", "slices_8", "slices_18", "no_cut")},
    {"title": "소스", "default": "소스 무관(기본)",
     "keys": ("tomato_sauce", "pesto_sauce", "no_sauce")},
)

TOPPINGS = {
    "pepperoni": "페퍼로니", "sausage": "소시지", "ham": "햄", "bacon": "베이컨", "chicken": "치킨",
    "duck": "오리", "anchovy": "앤초비", "shrimp": "새우", "scallop": "가리비",
    "mushroom": "버섯", "olive": "올리브", "onion": "양파", "bell_pepper": "피망",
    "jalapeno": "할라피뇨", "garlic": "마늘", "basil": "바질", "corn": "옥수수",
    "eggplant": "가지", "zucchini": "애호박", "artichoke": "아티초크", "pumpkin": "호박",
    "sliced_tomato": "토마토 슬라이스", "truffle": "트러플", "pineapple": "파인애플",
    "fig": "무화과", "peach": "복숭아", "apple": "사과", "avocado": "아보카도",
}

EXCLUDED_TOPPINGS = {
    "no_olive": "올리브 빼기", "no_bell_pepper": "피망 빼기", "no_ham": "햄 빼기", "no_pineapple": "파인애플 빼기",
    "no_basil": "바질 빼기", "no_corn": "옥수수 빼기", "no_artichoke": "아티초크 빼기", "no_duck": "오리 빼기",
    "no_onion": "양파 빼기", "no_mushroom": "버섯 빼기", "no_seafood": "해산물 전부 빼기", "no_veggies": "채소 전부 빼기",
}

CATEGORIES = {
    "category_meats": "모든 고기", "category_pork": "모든 돼지고기", "category_seafood": "모든 해산물",
    "category_fruits": "모든 과일", "category_veggies": "모든 채소", "category_fungi": "모든 버섯류",
    "category_green": "모든 초록 토핑", "category_white": "모든 흰 토핑", "category_spicy": "모든 매운 토핑",
    "category_vegetarian": "채식 토핑 전부", "category_vegan": "비건 토핑 전부",
    "category_peppers": "모든 고추류", "category_stinky": "모든 냄새 강한 토핑", "category_fish": "모든 생선",
    "category_all": "모든 토핑",
}

RECIPES = {
    "recipe_classic_meats": "Classic Meat", "recipe_meat_lovers": "Meat Lovers", "recipe_supreme": "Supreme",
    "recipe_hawaiian": "Hawaiian", "recipe_fruity_pig": "Fruity Pig", "recipe_green_dream": "Green Dream",
    "recipe_salty_sailor": "Salty Sailor", "recipe_stinky_pete": "Stinky Pete", "recipe_coastal_classic": "Coastal Classic",
    "recipe_puttanesca": "Puttanesca", "recipe_caprese": "Caprese", "recipe_sunset_medley": "Sunset Medley",
    "recipe_paradise_pie": "Paradise Pie", "recipe_apple_crisp": "Apple Crisp",
    "recipe_margherita": "Margherita", "recipe_capricciosa": "Capricciosa", "recipe_neapolitan": "Neapolitan",
    "recipe_flammkuchen": "Flammkuchen", "recipe_classic_greek": "Classic Greek", "recipe_pissaladiere": "Pissaladiere",
}

SIDE_GROUPS = (
    ("소스와 치즈", {key: label for key, (label, _) in SAUCE_CHEESE.items()}),
    ("토핑 추가", TOPPINGS),
    ("빼기", EXCLUDED_TOPPINGS),
    ("범주 전체", CATEGORIES),
    ("이름 붙은 레시피", RECIPES),
)
SIDE_KEYS = tuple(key for _, group in SIDE_GROUPS for key in group)
PIZZA_KEYS = tuple(PIZZA_OPTIONS)
STAGES = ("initial", "clarified")

GUIDE = """Fill the order form for each pizza. Tick only what the customer asks for in the text you were given.
- Sauce and cheese come by default. Tick tomato_sauce or pesto_sauce only when that sauce is asked for, and no_sauce or no_cheese only when they are left off.
- Tick at most one slice option and at most one of tomato_sauce, pesto_sauce and no_sauce. For a recipe with a requested sauce change, tick the recipe and the requested sauce.
- Keep a named recipe or a category as it is; do not expand it into ingredients. If the customer also lists ingredients, tick those too.
- A substitution such as "duck instead of ham" is duck plus no_ham.
- Write one pizza entry per pizza to make, after any arithmetic in the order: three pizzas are three entries. Their order does not matter.
- For a half-and-half pizza, set half_and_half and give two sides; which half is first does not matter. Options for the whole pizza go in both sides.
- Leave out other people's preferences and small talk. There is no free-text field."""


class FormError(ValueError):
    """The L document does not follow the form."""


def empty_side():
    return {key: False for key in SIDE_KEYS}


def empty_pizza():
    return {**{key: False for key in PIZZA_KEYS}, "sides": [empty_side()]}


def validate(document):
    """Check one stage (initial or clarified) and return it unchanged."""
    if not isinstance(document, dict) or set(document) != {"pizzas"}:
        raise FormError("L needs exactly pizzas")
    pizzas = document["pizzas"]
    if not isinstance(pizzas, list) or not pizzas:
        raise FormError("pizzas must list one entry per pizza")
    for index, pizza in enumerate(pizzas, 1):
        if not isinstance(pizza, dict) or set(pizza) != set(PIZZA_KEYS) | {"sides"}:
            raise FormError(f"pizza {index} must have exactly the pizza options and sides")
        if any(type(pizza[key]) is not bool for key in PIZZA_KEYS):
            raise FormError(f"pizza {index} options must be true or false")
        _check_single_choices(pizza, f"pizza {index}")
        sides = pizza["sides"]
        expected = 2 if pizza["half_and_half"] else 1
        if not isinstance(sides, list) or len(sides) != expected:
            raise FormError(f"pizza {index} needs {expected} side(s) for half_and_half={pizza['half_and_half']}")
        for side in sides:
            if not isinstance(side, dict) or set(side) != set(SIDE_KEYS):
                raise FormError(f"pizza {index} sides must have exactly the side options")
            if any(type(value) is not bool for value in side.values()):
                raise FormError(f"pizza {index} side options must be true or false")
            _check_single_choices(side, f"pizza {index} side")
    return document


def _check_single_choices(options, where):
    for choice in SINGLE_CHOICES:
        chosen = [key for key in choice["keys"] if options.get(key)]
        if len(chosen) > 1:
            raise FormError(f"{where} may tick only one of {', '.join(choice['keys'])}; got {', '.join(chosen)}")


def ticked(document):
    """A readable list of what is ticked, for review and failure reports."""
    lines = [f"pizzas={len(document['pizzas'])}"]
    for index, pizza in enumerate(document["pizzas"], 1):
        options = [key for key in PIZZA_KEYS if pizza[key] and key != "half_and_half"]
        sides = [" ".join(key for key in SIDE_KEYS if side[key]) or "(기본)" for side in pizza["sides"]]
        lines.append(f"pizza {index}: " + (" ".join(options) + " | " if options else "") + " / ".join(sides))
    return lines


def _pizza_key(pizza):
    sides = sorted(tuple(sorted(key for key in SIDE_KEYS if side[key])) for side in pizza["sides"])
    return (tuple(sorted(key for key in PIZZA_KEYS if pizza[key])), tuple(sides))


def _pizza_differences(expected, actual):
    differences = [f"{key}: expected {expected[key]}, got {actual[key]}"
                   for key in PIZZA_KEYS if expected[key] != actual[key]]
    if len(expected["sides"]) == len(actual["sides"]):
        best = None
        for order in permutations(actual["sides"]):
            found = [f"side {i}: {key} expected {e[key]}, got {a[key]}"
                     for i, (e, a) in enumerate(zip(expected["sides"], order), 1) for key in SIDE_KEYS if e[key] != a[key]]
            if best is None or len(found) < len(best):
                best = found
        differences += best
    return differences


def compare(expected, actual):
    """Exact match with unordered pizzas and unordered halves, plus the differing options."""
    validate(expected)
    try:
        validate(actual)
    except FormError as exc:
        return {"passed": False, "form_error": str(exc), "differences": []}
    if len(expected["pizzas"]) != len(actual["pizzas"]):
        return {"passed": False, "form_error": None,
                "differences": [f"number_of_pizzas: expected {len(expected['pizzas'])}, got {len(actual['pizzas'])}"]}
    remaining = list(actual["pizzas"])
    differences = []
    for index, wanted in enumerate(expected["pizzas"], 1):
        match = next((i for i, pizza in enumerate(remaining) if _pizza_key(pizza) == _pizza_key(wanted)), None)
        if match is not None:
            remaining.pop(match)
            continue
        # No exact match: report against the closest remaining pizza.
        closest = min(range(len(remaining)), key=lambda i: len(_pizza_differences(wanted, remaining[i])))
        differences += [f"pizza {index} {item}" for item in _pizza_differences(wanted, remaining.pop(closest))]
    return {"passed": not differences, "form_error": None, "differences": differences}


def from_ticks(*pizzas):
    """Build a stage from compact tick strings, used for drafts and tests.

    Each pizza is ``"pizza options : side options | side options"``; the part before
    ``:`` is optional and ``|`` makes the pizza half-and-half.
    """
    built = []
    for spec in pizzas:
        options, _, sides = spec.rpartition(":")
        pizza = empty_pizza()
        for key in options.split():
            if key not in PIZZA_KEYS:
                raise FormError(f"Unknown pizza option: {key}")
            pizza[key] = True
        parts = sides.split("|")
        pizza["half_and_half"] = len(parts) == 2
        pizza["sides"] = []
        for part in parts:
            side = empty_side()
            for key in part.split():
                if key not in SIDE_KEYS:
                    raise FormError(f"Unknown side option: {key}")
                side[key] = True
            pizza["sides"].append(side)
        built.append(pizza)
    return validate({"pizzas": built})


def schema_description():
    """The option sheet as text, given to models in the NLU task and to annotators."""
    lines = [f"Order form {FORM_VERSION}.", "", "Pizza options (true/false):"]
    lines += [f"- {key}: {english}" for key, (_, english) in PIZZA_OPTIONS.items()]
    lines += ["", "Side options (true/false), the same set on every side:"]
    lines += [f"- {key}: {english}" for key, (_, english) in SAUCE_CHEESE.items()]
    lines.append("- toppings to add: " + ", ".join(TOPPINGS))
    lines.append("- toppings or categories to leave out: " + ", ".join(EXCLUDED_TOPPINGS))
    lines.append("- every topping in a category: " + ", ".join(CATEGORIES))
    lines.append("- named recipes: " + ", ".join(f"{key} ({name})" for key, name in RECIPES.items()))
    lines += ["", GUIDE]
    return "\n".join(lines)


GUIDE_KO = """손님이 키오스크에서 주문서를 채운다고 생각하고, 손님이 주문한 것만 고릅니다.

작성 순서
1. 손님의 첫 말만 읽고 ① 첫 주문서를 작성합니다.
2. '네?'를 누르면 손님이 다시 한 말이 나옵니다. ② 주문서는 ①을 복사한 상태에서 시작하므로 바뀐 점만 고칩니다.
3. 아래에서 ①과 ②의 이해 난이도를 각각 고르고 '저장하고 다음'을 누릅니다.

피자
- 피자 한 판마다 탭이 하나입니다. 판이 더 있으면 '피자 추가'를 누릅니다. 피자 순서는 상관없습니다.
- '12명에게 4조각짜리로 한 조각씩'처럼 계산이 필요하면 계산한 판수만큼 만듭니다.
- 도우는 따로 요청이 없으면 '일반 도우(기본)'으로 두고, 밀 도우를 요청하면 '밀 도우'를 고릅니다.
- 조각 수는 따로 말이 없으면 '6조각(기본)'으로 둡니다.
- 반반 피자는 '반반'을 체크하고 두 반쪽을 각각 채웁니다. 피자 전체에 해당하는 재료는 두 반쪽에 모두 체크합니다. 어느 쪽이 먼저인지는 상관없습니다.

재료
- 소스와 치즈는 기본으로 들어갑니다. 소스 종류를 따로 말하지 않으면 '소스 무관(기본)'으로 둡니다. 손님이 토마토나 페스토를 요청하면 해당 소스를 고르고, 소스를 빼 달라고 하면 '소스 빼기'를 고릅니다. 치즈를 빼 달라고 하면 '치즈 빼기'를 체크합니다.
- 레시피 이름(Hawaiian 등)이나 '모든 고기' 같은 범주는 그대로 체크하고, 안에 든 재료를 따로 체크하지 않습니다. 손님이 재료를 따로 말했을 때만 그 재료도 체크합니다.
- 'A 대신 B'는 B를 체크하고 'A 빼기'를 체크합니다. 레시피의 소스를 바꿔 달라고 하면 레시피 이름을 체크하고 요청한 소스를 고릅니다.
- 다른 사람의 취향이나 잡담은 주문이 아니므로 체크하지 않습니다.

이해 난이도
- 손님의 말을 알아듣기가 얼마나 어려웠는지 하, 중, 상으로 고릅니다. 만들 피자가 복잡한지는 따지지 않습니다.
- ①은 첫 말만 들었을 때, ②는 다시 들은 말까지 들은 뒤의 난이도입니다.

저장
- '저장하고 다음'을 눌러야 그 문항이 완료됩니다. 작성 중인 문항도 자동으로 저장되며, 다시 열면 '작성 중'으로 이어서 할 수 있습니다."""
