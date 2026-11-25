"""Playable mock kitchen: python -m pizzabench.game."""

import argparse
from copy import copy, deepcopy
import json
import math
from pathlib import Path
import sys

from .environment import ToolError
from .execution_eval import assess_execution, validate_plan
from .game_orders import load_orders
from .game_render import INGREDIENTS, pizza as draw_pizza
from .kitchen import BRUSH_RADIUS, COATING_GRID, Kitchen, cut_angle, painted_cells


BG = "#f3eddf"
INK = "#332c25"
MUTED = "#827463"
GREEN = "#3e6553"
PAPER = "#fffaf0"
RED = "#b45440"
FONT = "Malgun Gothic"
ENGLISH100 = Path(__file__).resolve().parents[1] / "data" / "english100" / "benchmark_cases.jsonl"
TOPPING_SPACING = 0.15  # pizza radii between pieces placed by one drag
LOCATIONS = {"preparation": "준비대", "queued": "오븐 대기", "baking": "굽는 중",
             "oven_ready": "굽기 완료", "cutting": "커팅대", "submitted": "포장 완료"}


class GameSession:
    """Order visibility and grading stay outside the physical kitchen."""

    def __init__(self, order, *, oven_seconds=6, reference_plan=None):
        self.order = deepcopy(order)
        self.oven_seconds = oven_seconds
        self.reference_plan = None if reference_plan is None else deepcopy(validate_plan(reference_plan))
        self.reset()

    def reset(self):
        state = self.order.get("state")
        if state is not None and (state.get("environment_version") or self.order.get("environment_version") not in (None,"0.2")):
            self.kitchen = Kitchen.from_state(deepcopy(self.order["state"]))
            self.oven_seconds = self.kitchen.oven_seconds
        else:
            self.kitchen = Kitchen(oven_seconds=self.oven_seconds)
        self.initial_state = self.kitchen.snapshot()
        self.clarified = False
        self.finished = False
        self.score = None
        self.evaluation = None

    def observe(self):
        question = {"order_text": self.order["question"]["order_text"]}
        if self.clarified:
            question["clarification_text"] = self.order["question"]["clarification_text"]
        return {"question": question, "state": self.kitchen.snapshot()}

    def call(self, tool, args=None):
        if self.finished:
            raise ToolError("Start a new order before continuing")
        if tool == "clarify":
            if args not in (None, {}):
                raise ToolError("clarify takes no arguments")
            text = self.order["question"].get("clarification_text")
            if self.clarified or not text:
                raise ToolError("No further clarification is available")
            self.clarified = True
            result = {"clarification_text": text}
            self.kitchen.trace.append({"step": len(self.kitchen.trace) + 1,
                "time": self.kitchen.time, "tool": "clarify", "args": {}, "ok": True, "result": result})
            return result
        return self.kitchen.call(tool, args)

    def finish(self):
        if not self.kitchen.snapshot()["submitted"]:
            raise ToolError("Box every pizza before delivering the order")
        self.evaluation = assess_execution(self.order["answer"], self.kitchen.execution(),
                                           reference_plan=self.reference_plan)
        self.score = self.evaluation["outcome"]
        self.finished = True
        return self.score

    def report(self):
        return {"case_id": self.order["id"], "environment_version": self.kitchen.version,
                "task":"tool_use" if self.reference_plan is not None else "order_execution",
                "state": deepcopy(self.initial_state), "clarified": self.clarified,
                "execution": self.kitchen.execution(), "finished": self.finished,
                "score": deepcopy(self.score), "evaluation": deepcopy(self.evaluation)}


def run_plan(order, plan, *, oven_seconds=6):
    session = GameSession(order, oven_seconds=oven_seconds)
    if not isinstance(plan, list):
        raise ToolError("A plan must be an array of tool/args objects")
    for action in plan:
        if not isinstance(action, dict) or set(action) != {"tool", "args"}:
            raise ToolError("Each action requires tool and args")
        session.call(action["tool"], action["args"])
    session.finish()
    return session.report()


class GameWindow:
    PAPER, INK, MUTED, GREEN, RED, FONT = PAPER, INK, MUTED, GREEN, RED, FONT

    def __init__(self, root, orders, case_id="practice_olive", *, oven_seconds=6, data_path=None, key_file=None):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk, self.root = tk, ttk, root
        self.orders = {r["id"]: r for r in orders}
        self.labels = {r["label"]: r["id"] for r in orders}
        self.oven_seconds = oven_seconds
        self.selected = None
        self.tool = ("topping", "olive")
        self.stroke = []
        self.preview_cells = set()
        self.drag_start = None
        self.timer = None
        self.closed = False
        self.ai_running = False
        self.ingredient_buttons = {}
        root.title("Pizza Context Benchmark")
        root.geometry("1360x920")
        root.minsize(1120, 790)
        root.configure(bg=BG)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Kitchen.TCombobox", padding=7)

        top = tk.Frame(root, bg=GREEN, padx=18, pady=3)
        top.pack(fill="x")
        tk.Label(top, text="Pizza Context Benchmark", bg=GREEN, fg="#fff9e9",
                 font=(FONT, 11, "bold")).pack(side="left")
        from .game_panels import Panels
        from .credentials import KEY_FILE
        self.panels = Panels(self, root, data_path=data_path, key_file=key_file or KEY_FILE)

        customer = tk.Frame(root, bg=PAPER, padx=20, pady=12)
        customer.pack(fill="x", padx=18, pady=(8, 8))
        self.avatar = tk.Canvas(customer, width=64, height=68, bg=PAPER, highlightthickness=0)
        self.avatar.pack(side="left", padx=(0, 16))
        self.avatar.create_oval(7, 5, 55, 53, fill="#e3bd96", outline="")
        self.avatar.create_arc(5, 0, 58, 44, start=0, extent=180, fill="#665343", outline="")
        self.avatar.create_oval(20, 26, 24, 31, fill=INK, outline="")
        self.avatar.create_oval(39, 26, 43, 31, fill=INK, outline="")
        self.avatar.create_arc(25, 31, 39, 42, start=180, extent=180, outline="#925b45", style="arc", width=2)
        self.avatar.create_arc(2, 46, 61, 99, start=0, extent=180, fill="#8eab90", outline="")
        speech = tk.Frame(customer, bg=PAPER)
        speech.pack(side="left", fill="both", expand=True)
        tk.Label(speech, text="손님의 주문", bg=PAPER, fg=MUTED, font=(FONT, 9, "bold")).pack(anchor="w")
        self.order_label = tk.Label(speech, bg=PAPER, fg=INK, font=(FONT, 12),
                                    wraplength=900, justify="left", anchor="w")
        self.order_label.pack(fill="x", pady=4)
        customer.bind("<Configure>", lambda event: self.order_label.configure(wraplength=max(400, event.width-210)))
        self.clarification_var = tk.StringVar()
        tk.Label(speech, textvariable=self.clarification_var, bg=PAPER, fg=GREEN,
                 font=(FONT, 10), wraplength=900, justify="left").pack(anchor="w")
        self.clarify_button = self.button(customer, "네?", self.clarify, bg="#eee4cf", fg=INK, width=7)
        self.clarify_button.pack(side="right", padx=(12, 0))
        self.button(customer, "메뉴판", self.show_menu, bg="#eee4cf", fg=INK, width=7).pack(side="right", padx=(12, 0))


        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=18)
        left = tk.Frame(body, bg=PAPER, width=205, padx=10, pady=12)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        self.label(left, "재료 바구니", 12, True).pack(anchor="w", pady=(0, 8))
        base = tk.Frame(left, bg=PAPER)
        base.pack(fill="x")
        for col, (label, tool, kind, color) in enumerate([
            ("토마토\n소스", "sauce", "tomato", "#b95b48"),
            ("페스토\n소스", "sauce", "pesto", "#6f8755"),
            ("치즈", "cheese", None, "#b9933e")]):
            btn = self.button(base, label, lambda t=tool, k=kind: self.choose_tool(t, k), bg=color, width=1, padx=3)
            btn.grid(row=0, column=col, padx=2, sticky="ew")
            base.columnconfigure(col, weight=1, uniform="coatings")
            self.ingredient_buttons[(tool, kind)] = btn
        self.label(left, "바를 영역", 9).pack(anchor="w", pady=(10, 2))
        self.region_var = tk.StringVar(value="whole")
        mask = tk.Frame(left, bg=PAPER)
        mask.pack(fill="x")
        for name, value in [("전체", "whole"), ("왼쪽", "left"), ("오른쪽", "right")]:
            tk.Radiobutton(mask, text=name, variable=self.region_var, value=value, bg=PAPER,
                           activebackground=PAPER, fg=MUTED, font=(FONT, 9),
                           command=self.draw).pack(side="left")
        self.fill_button = self.button(left, "선택 영역에 넓게 바르기", self.fill_region,
                                       bg="#eee4cf", fg=INK)
        self.fill_button.pack(fill="x", pady=(5, 12))
        self.label(left, "토핑: 클릭하면 1개, 드래그하면 여러 개", 9).pack(anchor="w", pady=(0, 5))
        scroller = tk.Frame(left, bg=PAPER)
        scroller.pack(fill="both", expand=True)
        topping_canvas = tk.Canvas(scroller, bg=PAPER, highlightthickness=0, width=160)
        topping_scroll = ttk.Scrollbar(scroller, orient="vertical", command=topping_canvas.yview)
        topping_canvas.configure(yscrollcommand=topping_scroll.set)
        topping_scroll.pack(side="right", fill="y")
        topping_canvas.pack(side="left", fill="both", expand=True)
        toppings = tk.Frame(topping_canvas, bg=PAPER)
        topping_window = topping_canvas.create_window(0, 0, window=toppings, anchor="nw")
        toppings.bind("<Configure>", lambda _: topping_canvas.configure(scrollregion=topping_canvas.bbox("all")))
        topping_canvas.bind("<Configure>", lambda event: topping_canvas.itemconfigure(topping_window, width=event.width))
        def scroll_toppings(event):
            topping_canvas.yview_scroll(-int(event.delta/120), "units")
        topping_canvas.bind("<MouseWheel>", scroll_toppings)
        for index, (kind, (name, color)) in enumerate(INGREDIENTS.items()):
            button = self.button(toppings, name, lambda k=kind: self.choose_tool("topping", k),
                                 bg="#eee5d4", fg=INK, padx=3, pady=5, width=1)
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=2, pady=2)
            button.bind("<MouseWheel>", scroll_toppings)
            self.ingredient_buttons[("topping", kind)] = button
        toppings.columnconfigure(0, weight=1)
        toppings.columnconfigure(1, weight=1)

        center = tk.Frame(body, bg=BG)
        center.pack(side="left", fill="both", expand=True)
        self.pizza_tabs = tk.Frame(center, bg=BG)
        self.pizza_tabs.pack(fill="x", pady=(0, 7))
        self.canvas = tk.Canvas(center, bg="#e6d5b9", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self.draw())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", lambda _: self.canvas.delete("cursor"))
        self.metrics_var = tk.StringVar()
        tk.Label(center, textvariable=self.metrics_var, bg=PAPER, fg=INK,
                 font=(FONT, 10), anchor="w", padx=12, pady=10).pack(fill="x", pady=(6, 0))

        right_panel = tk.Frame(body, bg=PAPER, width=215)
        right_panel.pack(side="right", fill="y", padx=(10, 0))
        right_panel.pack_propagate(False)
        delivery = tk.Frame(right_panel, bg=PAPER, padx=12, pady=9)
        delivery.pack(side="bottom", fill="x")
        actions_canvas = tk.Canvas(right_panel, bg=PAPER, highlightthickness=0, width=190)
        actions_scroll = ttk.Scrollbar(right_panel, orient="vertical", command=actions_canvas.yview)
        actions_canvas.configure(yscrollcommand=actions_scroll.set)
        actions_scroll.pack(side="right", fill="y")
        actions_canvas.pack(side="left", fill="both", expand=True)
        right = tk.Frame(actions_canvas, bg=PAPER, padx=12, pady=12)
        actions_window = actions_canvas.create_window(0, 0, window=right, anchor="nw")
        right.bind("<Configure>", lambda _: actions_canvas.configure(scrollregion=actions_canvas.bbox("all")))
        actions_canvas.bind("<Configure>", lambda event: actions_canvas.itemconfigure(actions_window, width=event.width))
        def scroll_actions(event):
            actions_canvas.yview_scroll(-int(event.delta/120), "units")
        actions_canvas.bind("<MouseWheel>", scroll_actions)
        self.label(right, "만들기", 12, True).pack(anchor="w", pady=(0, 8))
        self.regular_button = self.button(right, "+ 일반 도우", lambda: self.create("regular"), bg=GREEN)
        self.regular_button.pack(fill="x", pady=3)
        self.button(right, "+ 밀 도우", lambda: self.create("wheat"), bg="#8b7553").pack(fill="x", pady=3)
        self.spread_button = self.button(right, "도우 펼치기", lambda: self.act("spread"), bg="#eee4cf", fg=INK)
        self.spread_button.pack(fill="x", pady=(12, 4))
        self.bake_button = self.button(right, "오븐에 굽기", lambda: self.act("bake"), bg="#ae6242")
        self.bake_button.pack(fill="x", pady=4)
        self.cutter_button = self.button(right, "커터 선택", lambda: self.choose_tool("cutter", None),
                                         bg="#eee4cf", fg=INK)
        self.cutter_button.pack(fill="x", pady=4)
        self.serve_button = self.button(right, "상자에 담기", lambda: self.act("serve"), bg=GREEN)
        self.serve_button.pack(fill="x", pady=4)
        tk.Frame(right, height=1, bg="#ded2bb").pack(fill="x", pady=14)
        self.button(right, "마지막 재료 취소", lambda: self.act("undo"), bg="#eee4cf", fg=INK).pack(fill="x", pady=3)
        self.button(right, "이 피자 버리기", lambda: self.act("discard"), bg="#eee4cf", fg=RED).pack(fill="x", pady=3)
        for widget in right.winfo_children():
            widget.bind("<MouseWheel>", scroll_actions)
        self.delivery_button = self.button(delivery, "손님께 전달 →", self.deliver, bg=GREEN, pady=11)
        self.delivery_button.pack(fill="x", pady=(0, 5))
        self.result_var = tk.StringVar()
        self.result_label = tk.Label(delivery, textvariable=self.result_var, bg=PAPER, fg=GREEN,
                                    font=(FONT, 10, "bold"), height=0, wraplength=185, justify="left")
        self.result_label.pack(anchor="w", pady=(2, 0))

        self.status_var = tk.StringVar()
        tk.Label(root, textvariable=self.status_var, bg=BG, fg=MUTED,
                 font=(FONT, 10), anchor="w", padx=22, pady=10).pack(fill="x")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.select_case(case_id)
        self.topping_points = []

    def label(self, parent, text, size=10, bold=False):
        return self.tk.Label(parent, text=text, bg=PAPER, fg=INK,
                             font=(FONT, size, "bold" if bold else "normal"))

    def button(self, parent, text, command, *, bg=GREEN, fg="#fffaf0", width=None, padx=10, pady=8):
        options = dict(text=text, command=command, bg=bg, fg=fg, activebackground=bg,
                       activeforeground=fg, relief="flat", bd=0, padx=padx, pady=pady,
                       font=(FONT, 10), cursor="hand2", disabledforeground="#aa9d87")
        if width is not None:
            options["width"] = width
        return self.tk.Button(parent, **options)

    @property
    def kitchen(self):
        return self.session.kitchen

    def select_case(self, case_id):
        if case_id not in self.orders:
            raise ValueError(f"Unknown order: {case_id}")
        self.session = GameSession(self.orders[case_id], oven_seconds=self.oven_seconds)
        self.order_var.set(self.orders[case_id]["label"])
        self.reset()
        self.panels.case_changed()

    def reset(self):
        self.session.reset()
        self.selected = None
        self.stroke = []
        self.preview_cells = set()
        self.drag_start = None
        self.tool = ("topping", "olive")
        self.region_var.set("whole")
        self.clarification_var.set("")
        self.result_var.set("")
        self.order_label.configure(text=self.session.order["question"]["order_text"])
        # Whether a clarification exists is learned by asking, as with the CLI clarify tool.
        self.clarify_button.configure(state="normal")
        self.status_var.set("")
        self.refresh()

    def blocked(self):
        """While a model plays, the shown kitchen belongs to it."""
        if self.ai_running:
            self.status_var.set("AI 실행 중에는 직접 조작할 수 없습니다. 중지 후 사용하세요.")
        return self.ai_running

    def choose_case(self, case_id):
        if self.blocked():
            self.order_var.set(self.session.order["label"])
            return
        self.select_case(case_id)

    def use_session(self, session):
        """Show a session created elsewhere, such as the one a model plays."""
        self.session = session
        self.selected = None
        self.stroke, self.preview_cells, self.drag_start = [], set(), None
        self.clarification_var.set("")
        self.result_var.set("")
        self.order_label.configure(text=session.order["question"]["order_text"])
        self.refresh()

    def apply_model_call(self, environment, text):
        """Run one model tool call on the shown kitchen, then redraw it."""
        response = environment.request(text)
        try:
            command = json.loads(text)
        except ValueError:
            command = {}
        args = command.get("args") if isinstance(command.get("args"), dict) else {}
        if response.get("ok") and command.get("tool") == "create":
            self.selected = response["result"]["id"]
        elif isinstance(args.get("pizza"), int) and args["pizza"] in self.kitchen.pizzas:
            self.selected = args["pizza"]
        if response.get("ok") and command.get("tool") == "clarify":
            self.clarification_var.set(response["result"]["clarification_text"])
        self.refresh()
        return response

    def show_outcome(self, evaluation, termination="finished"):
        if not evaluation:
            self.result_var.set("주문 미완료\n종료 이유: " + termination)
            return
        self.result_var.set("주문 성공" if evaluation["outcome"]["passed"] else "주문 조건 미충족")

    def clarify(self):
        if self.blocked():
            return
        try:
            result = self.session.call("clarify", {})
            self.clarification_var.set(result["clarification_text"])
        except ToolError as exc:
            self.error(exc)

    def show_menu(self):
        from tkinter.scrolledtext import ScrolledText
        from .menu import readable
        top = self.tk.Toplevel(self.root)
        top.title("메뉴판")
        top.geometry("760x620")
        self.menu_text = ScrolledText(top, font=(FONT, 10), wrap="word")
        self.menu_text.pack(fill="both", expand=True)
        self.menu_text.insert("1.0", readable())
        self.menu_text.configure(state="disabled")

    def choose_tool(self, item, kind):
        self.tool = (item, kind)
        self.refresh()

    def create(self, dough):
        if self.blocked():
            return
        try:
            result = self.session.call("create", {"dough": dough})
            self.selected = result["id"]
            self.status_var.set("")
        except ToolError as exc:
            self.error(exc)
        self.refresh()

    def error(self, exc):
        # The same error text a CLI client receives for this call.
        self.status_var.set("할 수 없는 동작: " + str(exc))

    def act(self, tool, **args):
        if self.blocked():
            return False
        if self.selected is None:
            self.status_var.set("할 수 없는 동작: 작업할 피자가 없습니다")
            return False
        try:
            self.session.call(tool, {"pizza": self.selected, **args})
            self.status_var.set("")
            if tool == "discard":
                self.selected = next((p.id for p in self.kitchen.pizzas.values() if p.location != "submitted"), None)
            self.refresh()
            return True
        except ToolError as exc:
            self.error(exc)
            self.refresh()
            return False

    def fill_region(self):
        item, kind = self.tool
        if item not in {"sauce", "cheese"}:
            self.status_var.set("할 수 없는 동작: 소스나 치즈가 선택되지 않았습니다")
            return
        region = self.region_var.get()
        args = {"item": item, "region": region}
        if kind is not None:
            args["kind"] = kind
        self.act("fill", **args)

    def select_pizza(self, pizza_id):
        self.selected = pizza_id
        self.stroke, self.drag_start = [], None
        self.preview_cells = set()
        self.refresh()

    def geometry(self):
        w, h = max(self.canvas.winfo_width(), 400), max(self.canvas.winfo_height(), 350)
        return w*.43, h*.54, min(w*.345, h*.385)

    def normalized(self, event):
        x, y, r = self.geometry()
        return (event.x-x)/r, (event.y-y)/r

    def on_press(self, event):
        if self.ai_running or self.session.finished or self.selected not in self.kitchen.pizzas:
            return
        pizza = self.kitchen.pizzas[self.selected]
        point = self.normalized(event)
        if math.hypot(*point) > 1.15:
            return
        if not pizza.spread and pizza.location == "preparation":
            self.act("spread")
        elif self.tool[0] == "topping":
            self.topping_points = [point]
            self.draw_topping_preview()
        elif self.tool[0] in {"sauce", "cheese"}:
            self.stroke = [point]
            self.preview_cells = painted_cells([point], self.region_var.get())
            self.draw()
        elif self.tool[0] == "cutter":
            self.drag_start = point

    def on_drag(self, event):
        point = self.normalized(event)
        if self.topping_points:
            if math.dist(self.topping_points[-1], point) >= TOPPING_SPACING:
                self.topping_points.append(point)
                self.draw_topping_preview()
        elif self.stroke:
            if len(self.stroke) < 2047:
                self.preview_cells.update(painted_cells([self.stroke[-1], point], self.region_var.get()))
                self.stroke.append(point)
                self.draw()
        elif self.drag_start is not None:
            cx, cy, radius = self.geometry()
            self.canvas.delete("drag")
            self.canvas.create_line(cx+self.drag_start[0]*radius, cy+self.drag_start[1]*radius,
                                    event.x, event.y, fill="#fdf7df", width=3, dash=(5, 3), tags="drag")

    def on_release(self, event):
        if self.topping_points:
            points, self.topping_points = self.topping_points, []
            self.canvas.delete("topping_preview")
            self.act("place_toppings", kind=self.tool[1], points=[list(p) for p in points])
        if self.stroke:
            points = [*self.stroke, self.normalized(event)]
            self.stroke = []
            self.preview_cells = set()
            self.paint_stroke(points)
        if self.drag_start is not None:
            start, self.drag_start = self.drag_start, None
            self.canvas.delete("drag")
            try:
                self.act("cut", angle=cut_angle(start, self.normalized(event)))
            except ToolError as exc:
                self.error(exc)

    def draw_topping_preview(self):
        cx, cy, radius = self.geometry()
        self.canvas.delete("topping_preview")
        for x, y in self.topping_points:
            self.canvas.create_oval(cx+x*radius-5, cy+y*radius-5, cx+x*radius+5, cy+y*radius+5,
                                    outline="#fff8dd", width=2, tags="topping_preview")

    def paint_stroke(self, points):
        item, kind = self.tool
        args = {"item": item, "points": [list(p) for p in points], "region": self.region_var.get()}
        if kind is not None:
            args["kind"] = kind
        self.act("paint", **args)

    def on_motion(self, event):
        self.canvas.delete("cursor")
        if self.tool[0] in {"sauce", "cheese"} and math.hypot(*self.normalized(event)) <= 1:
            _, _, radius = self.geometry()
            s = radius*BRUSH_RADIUS
            self.canvas.create_oval(event.x-s, event.y-s, event.x+s, event.y+s,
                                     outline="#fff8dd", width=2, tags="cursor")

    def tick(self):
        self.timer = None
        if self.closed:
            return
        self.timer = None

    def refresh(self, *, rebuild_tabs=True):
        signature = tuple((p.id, p.location, p.id == self.selected) for p in self.kitchen.pizzas.values())
        if signature != getattr(self, "_tab_signature", None):
            self._tab_signature = signature
            for child in self.pizza_tabs.winfo_children():
                child.destroy()
            if not self.kitchen.pizzas:
                self.tk.Label(self.pizza_tabs, text="피자 없음", bg=BG, fg=MUTED,
                              font=(FONT, 10), pady=5).pack(side="left")
            for p in self.kitchen.pizzas.values():
                label = f"#{p.id} · {LOCATIONS[p.location]}"
                self.button(self.pizza_tabs, label, lambda i=p.id: self.select_pizza(i),
                            bg=GREEN if p.id == self.selected else "#e6dbc7",
                            fg="#fffaf0" if p.id == self.selected else INK, padx=9, pady=6).pack(side="left", padx=(0, 5))
        p = self.kitchen.pizzas.get(self.selected)
        for key, button in self.ingredient_buttons.items():
            button.configure(highlightthickness=2, highlightbackground=GREEN if key == self.tool else PAPER)
        if p:
            state = p.snapshot()
            self.metrics_var.set(f"피자 #{p.id}  ·  {LOCATIONS[p.location]}  ·  토핑 {len(p.pieces)}개  ·  오븐 {p.oven_passes}회  ·  {state['cuts']}조각")
        else:
            self.metrics_var.set("")
        self.draw()

    def draw(self):
        if not hasattr(self, "session"):
            return
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 400), max(c.winfo_height(), 350)
        for y in range(0, int(h), 48):
            c.create_rectangle(0, y, w, y+48, fill="#dfc8a4" if y % 96 else "#e7d2b0", outline="#d1b991")
        cx, cy, radius = self.geometry()
        c.create_rectangle(cx-radius-18, cy-radius-27, cx+radius+18, cy+radius+29,
                           fill="#cbb18a", outline="#b89a70", width=2)
        c.create_rectangle(cx-radius-14, cy-radius-31, cx+radius+14, cy+radius+23,
                           fill="#f2dfbd", outline="#dfc59c", width=2)
        p = self.kitchen.pizzas.get(self.selected)
        stage_label = "커팅대" if p and p.location == "cutting" else "준비대"
        c.create_text(22, 25, text=stage_label, anchor="w", fill=INK, font=(FONT, 14, "bold"))
        item, kind = self.tool
        name = ("토마토 소스" if kind == "tomato" else "페스토 소스") if item == "sauce" else "치즈" if item == "cheese" else "커터" if item == "cutter" else INGREDIENTS[kind][0]
        c.create_text(22, 51, text="선택: " + name, anchor="w", fill=MUTED, font=(FONT, 10))
        if p and p.location in {"preparation", "cutting"}:
            drawing = p
            if self.stroke and p.location == "preparation" and self.tool[0] in {"sauce", "cheese"}:
                drawing = copy(p)
                drawing.coatings = deepcopy(p.coatings)
                key = self.tool[1] if self.tool[0] == "sauce" else "cheese"
                drawing.coatings[key] = sorted(set(drawing.coatings.get(key, [])) | self.preview_cells)
            draw_pizza(c, drawing, cx, cy, radius, guide=False)
        else:
            c.create_oval(cx-radius*.75, cy-radius*.75, cx+radius*.75, cy+radius*.75,
                           outline="#c9ac80", dash=(4, 6), width=2)
            text = "피자 없음" if p is None else LOCATIONS[p.location]
            c.create_text(cx, cy, text=text, fill="#a58d69", font=(FONT, 16, "bold"))
        ox = w*.86
        boxed = [p for p in self.kitchen.pizzas.values() if p.location == "submitted"]
        for i, value in enumerate(boxed[:4]):
            yy = h-100-i*22
            c.create_rectangle(ox-49, yy, ox+49, yy+60, fill="#d3b784", outline="#ac8c58", width=2)
            c.create_text(ox, yy+24, text=f"PIZZA #{value.id}", fill="#795b35", font=(FONT, 9, "bold"))
        c.create_text(ox, h-20, text=f"포장 {len(boxed)}판", fill=INK, font=(FONT, 10))

    def deliver(self):
        if self.blocked():
            return
        try:
            self.session.finish()
            self.show_outcome(self.session.evaluation)
            self.status_var.set("")
            self.panels.record_human(self.session.report())
            self.refresh()
        except ToolError as exc:
            self.error(exc)

    def close(self):
        self.closed = True
        self.panels.stop.set()
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Playable Q-SLATE mock pizza kitchen")
    parser.add_argument("--case", help="Case to open first; default is the first evaluation case")
    parser.add_argument("--data", type=Path,
                        help="Q-SLATE JSONL cases; the window defaults to the English 100 set")
    parser.add_argument("--api-keys", type=Path, help="Key file for model runs; default configs/api_keys.local.json")
    parser.add_argument("--oven-seconds", type=float, default=6)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--plan", type=Path, help="Coordinate-tool plan for headless execution")
    parser.add_argument("--output", type=Path)
    options = parser.parse_args(argv)
    try:
        data = options.data
        if data is None and not options.headless and ENGLISH100.exists():
            data = ENGLISH100
        orders = load_orders(data)
        if not options.headless:
            from .game_orders import PRACTICE
            practice = {r["id"] for r in PRACTICE}
            orders = [r for r in orders if r["id"] not in practice] or orders
        case_id = options.case or orders[0]["id"]
        order = next((r for r in orders if r["id"] == case_id), None)
        if order is None:
            raise ValueError(f"Unknown case: {case_id}")
        if options.headless:
            if options.plan is None:
                raise ValueError("--headless requires --plan")
            plan = json.loads(options.plan.read_text(encoding="utf-8-sig"))
            result = run_plan(order, plan, oven_seconds=options.oven_seconds)
            text = json.dumps(result, ensure_ascii=False, indent=2)+"\n"
            if options.output:
                options.output.write_text(text, encoding="utf-8")
            else:
                print(text)
            return 0 if result["score"]["passed"] else 1
        import tkinter as tk
        root = tk.Tk()
        GameWindow(root, orders, case_id, oven_seconds=options.oven_seconds,
                   data_path=data, key_file=options.api_keys)
        root.mainloop()
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
