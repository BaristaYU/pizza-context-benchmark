"""Original Canvas artwork; normalized ingredient geometry comes from Kitchen."""

import math

from .kitchen import COATING_GRID, GRID_STEP, GUIDE_POINTS


INGREDIENTS = {
    "pepperoni": ("페퍼로니", "#bb4236"), "sausage": ("소시지", "#82513c"),
    "mushroom": ("버섯", "#cfbb92"), "olive": ("올리브", "#3e4542"),
    "onion": ("양파", "#b582bd"), "bell_pepper": ("피망", "#4d8a50"),
    "pineapple": ("파인애플", "#edbf42"), "anchovy": ("앤초비", "#798f96"),
    "bacon": ("베이컨", "#c36a5a"), "ham": ("햄", "#e2958b"),
    "shrimp": ("새우", "#ed9c7d"), "corn": ("옥수수", "#f3cf4f"),
    "chicken": ("닭고기", "#d8bb8c"), "basil": ("바질", "#51835c"),
    "tomato": ("토마토", "#d55743"), "jalapeno": ("할라피뇨", "#337d49"),
    "garlic": ("마늘", "#f2e2ae"), "duck": ("오리", "#a86a4b"),
    "fig": ("무화과", "#a85f84"), "zucchini": ("주키니", "#85a564"),
    "artichoke": ("아티초크", "#9aaa67"), "avocado": ("아보카도", "#a9bd68"),
    "eggplant": ("가지", "#80649a"), "truffle": ("트러플", "#51463e"),
    "tofu": ("두부", "#eee2cb"), "potato": ("감자", "#c5a765"),
    "pork_belly": ("삼겹살", "#c58c79"), "pumpkin": ("호박", "#dd933a"),
    "rose_petal": ("장미 꽃잎", "#b85271"), "peach": ("복숭아", "#e9a46e"),
    "apple": ("사과", "#c36448"), "scallop": ("관자", "#e6d5b0"),
}


def ingredient(canvas, kind, x, y, size=10, tag="pizza"):
    color = INGREDIENTS.get(kind, (kind, "#b57853"))[1]
    s = size
    kw = {"tags": tag}
    if kind in {"olive", "onion", "jalapeno", "tomato", "zucchini"}:
        canvas.create_oval(x-s, y-s, x+s, y+s, fill=color, outline="", **kw)
        canvas.create_oval(x-s*.50, y-s*.50, x+s*.50, y+s*.50, fill="#edcf86", outline="", **kw)
        if kind == "onion":
            canvas.create_arc(x-s*.78, y-s*.78, x+s*.78, y+s*.78, start=15, extent=280,
                              style="arc", outline="#e5b9dd", width=max(1, s*.16), **kw)
    elif kind == "mushroom":
        canvas.create_rectangle(x-s*.27, y, x+s*.27, y+s, fill="#e3d4b4", outline="", **kw)
        canvas.create_arc(x-s, y-s, x+s, y+s*.6, start=0, extent=180,
                          fill=color, outline="#9f8a6b", style="pieslice", **kw)
    elif kind in {"bell_pepper", "shrimp"}:
        canvas.create_arc(x-s, y-s, x+s, y+s, start=20, extent=265,
                          outline=color, width=max(2, s*.55), style="arc", **kw)
    elif kind in {"basil", "avocado", "artichoke"}:
        canvas.create_oval(x-s*.65, y-s, x+s*.65, y+s, fill=color, outline="", **kw)
        canvas.create_line(x, y-s*.7, x, y+s*.7, fill="#c4d199", **kw)
    elif kind in {"ham", "bacon", "pineapple", "garlic", "chicken", "duck"}:
        canvas.create_polygon(x-s, y-s*.6, x+s*.6, y-s, x+s, y+s*.6, x-s*.7, y+s,
                              fill=color, outline="", **kw)
        if kind == "bacon":
            canvas.create_line(x-s*.7, y-s*.4, x+s*.7, y+s*.4, fill="#f1b39b", width=2, **kw)
    else:
        canvas.create_oval(x-s, y-s*.85, x+s, y+s*.85, fill=color, outline="", **kw)
        if kind == "pepperoni":
            for dx, dy in [(-.35, -.25), (.25, .38), (.4, -.3)]:
                canvas.create_oval(x+(dx-.1)*s, y+(dy-.1)*s, x+(dx+.1)*s, y+(dy+.1)*s,
                                   fill="#e88760", outline="", **kw)
        elif kind == "fig":
            canvas.create_oval(x-s*.6, y-s*.6, x+s*.6, y+s*.6, fill="#e6a18d", outline="", **kw)


def pizza(canvas, value, x, y, radius, *, guide=False):
    """Draw every actual piece and coating cell; never regenerate positions."""
    r = radius if value.spread else radius*.43
    burns = min(value.oven_passes, 4)
    crust = ["#ddb879", "#cc985b", "#af763f", "#79502f", "#4d382b"][burns]
    if value.dough == "wheat":
        crust = ["#bc925d", "#a77947", "#8d6038", "#674730", "#443326"][burns]
    canvas.create_oval(x-r-4, y-r+5, x+r+4, y+r+12, fill="#bca482", outline="", tags="pizza")
    canvas.create_oval(x-r, y-r, x+r, y+r, fill=crust, outline="#a27647", width=2, tags="pizza")
    canvas.create_oval(x-r*.91, y-r*.91, x+r*.91, y+r*.91, fill="#f2d698", outline="", tags="pizza")
    for i in range(20):
        a = i * 2.399963
        rr = r*(.93 if i % 2 else .96)
        cx, cy = x+math.cos(a)*rr, y+math.sin(a)*rr
        canvas.create_oval(cx-2, cy-1.5, cx+2, cy+1.5, fill="#b5854d", outline="", tags="pizza")
    if not value.spread:
        canvas.create_arc(x-r*.6, y-r*.6, x+r*.6, y+r*.6, start=20, extent=210,
                          outline="#e8ca8f", width=3, style="arc", tags="pizza")
        return
    for kind in [k for k in value.coatings if k != "cheese"] + ["cheese"]:
        color = {"tomato": "#ba503c", "pesto": "#6c8750", "cheese": "#efcb74"}.get(kind, "#b57853")
        for cell in value.coatings.get(kind, []):
            px, py = COATING_GRID[cell]
            cx, cy, s = x+px*r, y+py*r, r*GRID_STEP*.73
            canvas.create_oval(cx-s, cy-s, cx+s, cy+s, fill=color, outline="", tags="pizza")
            if kind == "cheese" and cell % 7 == 0:
                canvas.create_line(cx-s*.5, cy, cx+s*.4, cy+s*.35,
                                   fill="#fae4a6", width=max(1, r*.012), tags="pizza")
    if guide and value.location == "preparation":
        for px, py in GUIDE_POINTS:
            s = max(3, r*.037)
            canvas.create_oval(x+px*r-s, y+py*r-s, x+px*r+s, y+py*r+s,
                               outline="#b09a6d", dash=(2, 3), tags="pizza")
        canvas.create_line(x, y-r*.85, x, y+r*.85, fill="#c9b58e", dash=(4, 5), tags="pizza")
    for point in value.pieces:
        ingredient(canvas, point["kind"], x+point["x"]*r, y+point["y"]*r, max(3, r*.052))
    for angle in value.cut_angles:
        a = math.radians(angle)
        dx, dy = math.cos(a)*r*.98, math.sin(a)*r*.98
        canvas.create_line(x-dx, y-dy, x+dx, y+dy, fill="#8f7049", width=max(1, r*.012), tags="pizza")
        canvas.create_line(x-dx+1, y-dy+1, x+dx+1, y+dy+1, fill="#f8e2af", width=1, tags="pizza")
