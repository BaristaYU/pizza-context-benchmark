"""Assistant-drafted L order forms for the English 100 cases (form l-form-v3).

Each entry gives the initial form (order text only) and the clarified form (order text
plus the clarification), as compact tick strings for ``linguistics_form.from_ticks``.
Keys are the order's place in the wiki data, "entry:order" (see ``wiki_orders``), so a
draft stays with its order when the selection or the case numbering changes. These are drafts for comparison with the team's
independent answers, not ground truth. The clarified form must lead to the case's A
through the menu; tests check this with ``l_to_a``.
"""

from .linguistics_form import from_ticks


def same(*pizzas):
    return (pizzas, pizzas)


def times(count, spec):
    return (spec,) * count


DRAFTS = {
    "12:0": (("basil",), ("wheat_dough : basil",)),
    "588:0": same("tomato_sauce category_meats | tomato_sauce eggplant"),
    "427:0": same("recipe_meat_lovers", *times(2, "recipe_green_dream")),
    "430:0": (("category_meats",), ("pepperoni sausage",)),
    "499:0": same(*times(2, "tomato_sauce recipe_puttanesca")),
    "582:0": same("slices_8 : category_spicy | category_fruits"),
    "387:0": same(*times(2, "basil apple")),
    "530:1": same("category_all"),
    "380:0": same(*times(3, "slices_8 : apple onion pepperoni")),
    "364:0": same("chicken peach"),
    "41:2": same("bake_twice : no_sauce"),
    "221:0": same("pesto_sauce chicken", "pesto_sauce olive", "pesto_sauce mushroom"),
    "154:0": same("pineapple olive"),
    "639:0": (("pesto_sauce category_seafood",), ("pesto_sauce category_seafood anchovy shrimp",)),
    "557:0": same("bake_twice : no_sauce no_cheese category_fungi"),
    "623:0": same("recipe_meat_lovers category_spicy", *times(2, "category_veggies")),
    "648:0": (("",), ("apple category_seafood",)),
    "276:0": same("pesto_sauce avocado corn bacon"),
    "209:0": same("pepperoni corn"),
    "541:0": same("recipe_coastal_classic", "category_meats"),
    "100:0": same("olive"),
    "549:6": same("category_fruits"),
    "650:0": same("slices_8 : category_seafood avocado", "slices_8 : recipe_fruity_pig avocado",
             "slices_8 : recipe_stinky_pete avocado"),
    "384:0": same("apple pineapple"),
    "613:0": same("category_meats | category_seafood"),
    "481:0": (("recipe_meat_lovers", "recipe_meat_lovers", "pesto_sauce recipe_meat_lovers"),
         ("tomato_sauce recipe_meat_lovers", "tomato_sauce recipe_meat_lovers", "pesto_sauce recipe_meat_lovers")),
    "331:9": (("",), ("pumpkin",)),
    "440:1": same(*times(2, "recipe_coastal_classic")),
    "443:0": same("recipe_coastal_classic", "no_sauce scallop truffle"),
    "214:0": same("chicken"),
    "44:2": same(*times(2, "bake_twice : ")),
    "604:1": same("wheat_dough : category_meats | no_sauce no_cheese jalapeno"),
    "46:2": same("pesto_sauce"),
    "656:0": same("bake_twice : recipe_classic_meats category_spicy"),
    "426:0": same("recipe_classic_meats", "recipe_meat_lovers", "recipe_green_dream"),
    "219:0": same(*times(2, "chicken onion")),
    "272:0": (("pesto_sauce",), ("pesto_sauce avocado bell_pepper",)),
    "611:1": same("wheat_dough : category_vegetarian | no_sauce no_cheese anchovy"),
    "228:0": (("chicken",), ("chicken corn",)),
    "668:3": (("no_cheese",), ("category_vegan",)),
    "156:0": (("",), ("pepperoni bell_pepper pineapple",)),
    "107:0": same(*times(3, "olive sausage")),
    "58:10": same("pepperoni"),
    "408:3": same("recipe_apple_crisp"),
    "335:0": same("pumpkin olive onion", "pumpkin sausage", "pumpkin"),
    "165:5": same("ham"),
    "227:0": (("chicken | pesto_sauce shrimp",), ("tomato_sauce chicken | pesto_sauce shrimp",)),
    "299:0": same("pesto_sauce basil fig", *times(2, "pesto_sauce recipe_fruity_pig")),
    "365:0": same("peach garlic"),
    "461:0": same("recipe_salty_sailor | recipe_stinky_pete"),
    "27:0": (("wheat_dough : zucchini shrimp basil",), ("wheat_dough : pesto_sauce shrimp | no_sauce no_cheese zucchini",)),
    "353:2": same("peach"),
    "615:0": same("tomato_sauce category_meats | artichoke"),
    "685:0": same("recipe_fruity_pig", "category_vegetarian"),
    "630:0": same("category_pork"),
    "247:0": (("sliced_tomato",), ("pesto_sauce sliced_tomato | tomato_sauce sliced_tomato",)),
    "316:0": same("pesto_sauce recipe_green_dream", "pesto_sauce recipe_stinky_pete", "pesto_sauce onion zucchini jalapeno"),
    "263:0": same("pineapple jalapeno"),
    "110:0": same("pepperoni mushroom olive sausage", ""),
    "691:1": same("category_vegetarian", "duck"),
    "480:0": same("tomato_sauce recipe_meat_lovers"),
    "32:0": same("pumpkin corn", "wheat_dough : pumpkin corn"),
    "687:0": same("recipe_capricciosa", "category_vegetarian"),
    "244:0": (("slices_8 : ",), ("slices_8 : sliced_tomato",)),
    "580:1": same("category_meats | category_green"),
    "253:0": same("pesto_sauce no_cheese chicken | no_sauce no_cheese chicken sliced_tomato"),
    "14:0": (("wheat_dough : onion",), ("wheat_dough : onion basil",)),
    "328:0": same("recipe_classic_meats recipe_capricciosa"),
    "51:0": same(*times(2, "no_cheese | no_sauce")),
    "301:0": same("chicken corn basil fig"),
    "513:0": (("recipe_supreme category_vegan",), ("no_cheese mushroom olive onion bell_pepper",)),
    "612:0": same("wheat_dough : pesto_sauce category_vegetarian | no_sauce no_cheese duck"),
    "336:0": same("pumpkin basil"),
    "542:0": same("wheat_dough : category_meats"),
    "347:0": same("duck fig"),
    "585:1": same("category_meats | category_fruits"),
    "609:1": same("wheat_dough : category_vegetarian | no_sauce no_cheese duck"),
    "151:4": same("pineapple"),
    "696:0": same("fig category_veggies"),
    "548:0": same("bake_twice : category_fruits | "),
    "491:7": same("recipe_paradise_pie"),
    "202:0": (("no_cheese",), ("tomato_sauce no_cheese pepperoni ham shrimp bacon",)),
    "172:0": same(*times(3, "pesto_sauce ham | pesto_sauce onion")),
    "206:5": same("corn"),
    "330:0": same("no_sauce no_cheese pumpkin"),
    "126:0": same("pesto_sauce mushroom sausage", "pesto_sauce mushroom sausage onion | pesto_sauce mushroom sausage"),
    "661:0": same("peach category_spicy"),
    "704:0": same("category_white | "),
    "543:0": same(*times(2, "wheat_dough : category_meats")),
    "194:0": (("",), ("eggplant bell_pepper onion basil",)),
    "554:0": (("wheat_dough : category_fruits",), ("wheat_dough : category_fruits truffle",)),
    "616:0": same("wheat_dough : pesto_sauce category_meats | no_sauce no_cheese apple"),
    "592:0": same("tomato_sauce no_cheese category_meats | zucchini"),
    "664:0": same("recipe_sunset_medley", "recipe_sunset_medley category_green"),
    "533:0": same("tomato_sauce category_meats"),
    "171:0": same("olive onion | no_sauce no_cheese ham"),
    "438:0": (("wheat_dough : recipe_classic_meats zucchini category_peppers",),
              ("wheat_dough : tomato_sauce pepperoni sausage zucchini category_peppers",)),
    "98:0": (("no_cheese",), ("tomato_sauce no_cheese olive | pesto_sauce no_cheese",)),
    "134:0": same("pesto_sauce pepperoni sausage", "pesto_sauce mushroom | pesto_sauce olive onion"),
    "517:0": same("recipe_supreme tomato_sauce | recipe_supreme pesto_sauce"),
}

NOTES = {}


def draft(key):
    """The initial and clarified L forms for one wiki order ("entry:order")."""
    initial, clarified = DRAFTS[key]
    return from_ticks(*initial), from_ticks(*clarified)
