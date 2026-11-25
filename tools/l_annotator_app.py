# -*- coding: utf-8 -*-
"""피자 주문서(L) 작성 도구.

Python만 설치되어 있으면 추가 설치 없이 실행됩니다(tkinter만 사용). 배포용 파일은
scripts/build_l_annotator.py가 문항과 문항지를 이 파일에 넣어 만듭니다.
결과는 이 파일과 같은 폴더의 L_결과_<이름>.json에 저장됩니다. '저장하고 다음'으로 완료한
문항은 answers에, 작성 중인 문항은 다른 문항으로 옮길 때, 창을 닫을 때, 30초마다 drafts에
저장됩니다.
"""

import json
import os
import sys
from copy import deepcopy
from datetime import datetime

EMBEDDED = None  # 배포 파일을 만들 때 문항지와 문항으로 채워진다.

FONT = "Malgun Gothic"
BG, PAPER, INK, MUTED, GREEN, ORANGE = "#f3eddf", "#fffaf0", "#332c25", "#827463", "#3e6553", "#b5652d"
DIFFICULTIES = ("하", "중", "상")
NOT_CHOSEN = "\x00"  # Tk shows a radio button whose value matches its tristate value as half-selected.
AUTOSAVE_MS = 30000
STAGES = (("initial", "① 첫 말만 들었을 때 이해 난이도"), ("clarified", "② 다시 들은 뒤 이해 난이도"))


def here():
    return os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else __file__))


def empty_side(data):
    return {key: False for key in data["side_keys"]}


def empty_pizza(data):
    pizza = {key: False for key in data["pizza_keys"]}
    pizza["sides"] = [empty_side(data)]
    return pizza


def empty_form(data):
    return {"pizzas": [empty_pizza(data)]}


def empty_state(data):
    return {"initial": empty_form(data), "clarified": None, "heard_again": False,
            "difficulty": {"initial": "", "clarified": ""}}


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Results:
    """One JSON file per annotator; written whole each time so it never half-saves."""

    def __init__(self, folder, name, data):
        self.path = os.path.join(folder, "L_결과_%s.json" % name)
        self.name, self.data = name, data
        self.answers, self.drafts = {}, {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.answers, self.drafts = saved.get("answers", {}), saved.get("drafts", {})

    def write(self):
        value = {"format": "l-annotation-v2", "form_version": self.data["form_version"], "annotator": self.name,
                 "updated_at": now(), "answers": self.answers, "drafts": self.drafts}
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=1)
        os.replace(temporary, self.path)

    def save(self, case_id, number, state):
        self.answers[case_id] = {"number": number, "initial": deepcopy(state["initial"]),
                                 "clarified": deepcopy(state["clarified"]),
                                 "difficulty": dict(state["difficulty"]), "saved_at": now()}
        self.drafts.pop(case_id, None)
        self.write()

    def save_draft(self, case_id, state):
        self.drafts[case_id] = dict(deepcopy(state), saved_at=now())
        self.write()

    def state(self, case_id, data):
        """The work to show for a case: an unfinished draft first, then the saved answer."""
        if case_id in self.drafts:
            draft = deepcopy(self.drafts[case_id])
            draft.pop("saved_at", None)
            return draft, "저장하지 않았던 작업을 불러왔습니다. '저장하고 다음'을 눌러야 완료됩니다."
        if case_id in self.answers:
            answer = self.answers[case_id]
            return ({"initial": deepcopy(answer["initial"]), "clarified": deepcopy(answer["clarified"]),
                     "heard_again": True, "difficulty": dict(answer["difficulty"])}, "저장된 답을 불러왔습니다.")
        return empty_state(data), ""


class App:
    def __init__(self, root, data, folder=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.root, self.data = tk, ttk, root, data
        self.folder = folder or here()
        self.results = None
        self.index = 0
        self.sheets = {}
        self.heard_again = False
        self.loaded = None
        self.keep, self.drawing = {}, None  # Tk variables behind each sheet's visible check boxes
        root.title("피자 주문서 작성 도구")
        width, height = min(1280, root.winfo_screenwidth() - 40), min(900, root.winfo_screenheight() - 80)
        root.geometry("%dx%d+10+10" % (width, height))
        root.configure(bg=BG)
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        top = tk.Frame(root, bg=GREEN, padx=14, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="작성자 이름", bg=GREEN, fg="white", font=(FONT, 10)).pack(side="left")
        self.name_var = tk.StringVar()
        tk.Entry(top, textvariable=self.name_var, width=12, font=(FONT, 10)).pack(side="left", padx=(6, 4))
        tk.Button(top, text="시작", command=self.start).pack(side="left")
        tk.Label(top, text="   문항", bg=GREEN, fg="white", font=(FONT, 10)).pack(side="left")
        self.case_var = tk.StringVar()
        self.case_box = ttk.Combobox(top, textvariable=self.case_var, state="readonly", width=22)
        self.case_box.pack(side="left", padx=6)
        self.case_box.bind("<<ComboboxSelected>>", lambda _: self.go(self.case_box.current()))
        self.progress_var = tk.StringVar(value="이름을 적고 시작을 누르세요.")
        tk.Label(top, textvariable=self.progress_var, bg=GREEN, fg="white", font=(FONT, 10, "bold")).pack(side="left", padx=12)
        tk.Button(top, text="작성 안내", command=self.show_guide).pack(side="right")

        customer = tk.Frame(root, bg=PAPER, padx=16, pady=10)
        customer.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(customer, text="손님", bg=PAPER, fg=MUTED, font=(FONT, 9, "bold")).pack(anchor="w")
        self.order_label = tk.Label(customer, bg=PAPER, fg=INK, font=(FONT, 13), wraplength=1080, justify="left", anchor="w")
        self.order_label.pack(fill="x", pady=(2, 4))
        self.again_label = tk.Label(customer, bg=PAPER, fg=GREEN, font=(FONT, 12), wraplength=1080, justify="left", anchor="w")
        self.again_label.pack(fill="x")
        self.again_button = tk.Button(customer, text="네? (다시 듣기)", command=self.hear_again, font=(FONT, 10))
        self.again_button.place(relx=1.0, x=-6, y=4, anchor="ne")

        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill="both", expand=True, padx=12)
        for stage, title in (("initial", "① 첫 주문서  (손님의 첫 말만 듣고 작성)"),
                             ("clarified", "② '네?' 이후 주문서  (다시 들은 말까지 반영해 작성)")):
            frame = tk.Frame(self.tabs, bg=BG)
            self.tabs.add(frame, text=title)
            self.sheets[stage] = {"frame": frame, "form": None}
        bottom = tk.Frame(root, bg=BG, padx=12, pady=6)
        bottom.pack(fill="x", side="bottom", before=self.tabs)  # always visible on short screens
        ratings = tk.Frame(bottom, bg=BG)
        ratings.pack(side="left")
        self.difficulty_vars, self.difficulty_buttons = {}, {}
        for row, (stage, title) in enumerate(STAGES):
            tk.Label(ratings, text=title, bg=BG, fg=INK, font=(FONT, 10, "bold"), anchor="w"
                     ).grid(row=row, column=0, sticky="w", padx=(0, 8))
            self.difficulty_vars[stage] = tk.StringVar()
            self.difficulty_buttons[stage] = []
            for column, level in enumerate(DIFFICULTIES, 1):
                button = tk.Radiobutton(ratings, text=level, value=level, variable=self.difficulty_vars[stage],
                                        tristatevalue=NOT_CHOSEN, bg=BG, font=(FONT, 10))
                button.grid(row=row, column=column, padx=4)
                self.difficulty_buttons[stage].append(button)
        self.status_var = tk.StringVar()
        tk.Label(bottom, textvariable=self.status_var, bg=BG, fg=ORANGE, font=(FONT, 10), wraplength=520,
                 justify="left").pack(side="left", padx=16)
        tk.Button(bottom, text="저장하고 다음 →", command=self.save_next, bg=GREEN, fg="white",
                  font=(FONT, 11, "bold"), padx=14).pack(side="right")
        tk.Button(bottom, text="← 이전", command=lambda: self.go(self.index - 1)).pack(side="right", padx=8)
        self.set_enabled(False)
        self.root.after(AUTOSAVE_MS, self.autosave)

    # ----- session --------------------------------------------------------------
    def set_enabled(self, enabled):
        self.tabs.tab(1, state="normal" if enabled and self.heard_again else "disabled")
        self.again_button.configure(state="normal" if enabled else "disabled")
        for stage, buttons in self.difficulty_buttons.items():
            usable = enabled and (stage == "initial" or self.heard_again)
            for button in buttons:
                button.configure(state="normal" if usable else "disabled")

    def collect(self):
        """What is on screen now, in the shape Results stores."""
        return {"initial": deepcopy(self.sheets["initial"]["form"]),
                "clarified": deepcopy(self.sheets["clarified"]["form"]),
                "heard_again": self.heard_again,
                "difficulty": {stage: var.get() for stage, var in self.difficulty_vars.items()}}

    def stash(self):
        """Keep unfinished work on the current case when leaving it."""
        if self.results is None or self.loaded is None:
            return
        state = self.collect()
        if state != self.loaded:
            self.results.save_draft(self.data["questions"][self.index]["id"], state)
            self.loaded = state

    def autosave(self):
        """Also keep work in progress every half minute, in case the computer turns off."""
        try:
            self.stash()
        finally:
            self.root.after(AUTOSAVE_MS, self.autosave)

    def close(self):
        self.stash()
        self.root.destroy()

    def start(self):
        name = self.name_var.get().strip()
        if not name or any(ch in name for ch in '\\/:*?"<>|'):
            self.progress_var.set("이름을 적어 주세요(파일 이름에 쓸 수 없는 기호 제외).")
            return
        self.stash()
        self.loaded = None
        self.results = Results(self.folder, name, self.data)
        ids = [q["id"] for q in self.data["questions"]]
        drafts = [i for i, case_id in enumerate(ids) if case_id in self.results.drafts]
        undone = [i for i, case_id in enumerate(ids) if case_id not in self.results.answers]
        self.go((drafts or undone or [0])[0])

    def labels(self):
        marks = []
        for q in self.data["questions"]:
            mark = ""
            if self.results is not None and q["id"] in self.results.drafts:
                mark = "  … 작성 중"
            elif self.results is not None and q["id"] in self.results.answers:
                mark = "  ✓ 완료"
            marks.append("%d번%s" % (q["number"], mark))
        return marks

    def go(self, index):
        if self.results is None:
            return
        self.stash()
        index = max(0, min(index, len(self.data["questions"]) - 1))
        self.index = index
        question = self.data["questions"][index]
        state, message = self.results.state(question["id"], self.data)
        self.case_box.configure(values=self.labels())
        self.case_box.current(index)
        done = len(set(self.results.answers) - set(self.results.drafts))
        self.progress_var.set("%s님 · 완료 %d / %d" % (self.results.name, done, len(self.data["questions"])))
        self.order_label.configure(text=question["order_text"])
        self.heard_again = state["heard_again"]
        self.again_label.configure(text=self.again_text(question) if self.heard_again else "")
        self.sheets["initial"]["form"] = state["initial"]
        self.sheets["clarified"]["form"] = state["clarified"]
        for stage, var in self.difficulty_vars.items():
            var.set(state["difficulty"].get(stage, ""))
        self.status_var.set(message)
        self.loaded = self.collect()
        self.set_enabled(True)
        self.tabs.select(0)
        for stage in self.sheets:
            self.draw(stage)

    @staticmethod
    def again_text(question):
        return "다시 들은 말: " + (question["clarification_text"] or "(더 할 말이 없습니다)")

    def hear_again(self):
        question = self.data["questions"][self.index]
        self.heard_again = True
        self.again_label.configure(text=self.again_text(question))
        if self.sheets["clarified"]["form"] is None:
            # 두 번째 주문서는 첫 주문서에서 시작해 바뀐 점만 고치면 된다.
            self.sheets["clarified"]["form"] = deepcopy(self.sheets["initial"]["form"])
            self.draw("clarified")
        self.set_enabled(True)
        self.tabs.select(1)

    def save_next(self):
        if self.results is None:
            self.progress_var.set("이름을 적고 시작을 누르세요.")
            return
        if not self.heard_again:
            self.status_var.set("'네?'를 눌러 손님의 말을 다시 듣고 ② 주문서도 작성해 주세요.")
            return
        for stage, title in STAGES:
            if not self.difficulty_vars[stage].get():
                self.status_var.set("%s를 골라 주세요." % title)
                return
        question = self.data["questions"][self.index]
        self.results.save(question["id"], question["number"], self.collect())
        self.loaded = None
        if not self.results.drafts and len(self.results.answers) == len(self.data["questions"]):
            self.status_var.set("모든 문항을 저장했습니다. %s 파일을 보내 주세요." % os.path.basename(self.results.path))
        self.go(self.index + 1 if self.index + 1 < len(self.data["questions"]) else self.index)

    # ----- one order sheet ---------------------------------------------------------
    def draw(self, stage):
        tk, ttk = self.tk, self.ttk
        sheet = self.sheets[stage]
        for child in sheet["frame"].winfo_children():
            child.destroy()
        self.keep[stage] = []
        self.drawing = stage
        form = sheet["form"]
        if form is None:
            tk.Label(sheet["frame"], text="위의 '네?'를 눌러 손님의 말을 다시 들으면 작성할 수 있습니다.",
                     bg=BG, fg=MUTED, font=(FONT, 11)).pack(pady=30)
            return
        bar = tk.Frame(sheet["frame"], bg=BG, pady=4)
        bar.pack(fill="x")
        tk.Label(bar, text="피자 %d판" % len(form["pizzas"]), bg=BG, fg=INK, font=(FONT, 11, "bold")).pack(side="left")
        tk.Button(bar, text="+ 피자 추가", command=lambda: self.add_pizza(stage)).pack(side="left", padx=8)
        pizzas = ttk.Notebook(sheet["frame"])
        pizzas.pack(fill="both", expand=True)
        sheet["pizzas"] = pizzas
        for number, pizza in enumerate(form["pizzas"], 1):
            pizzas.add(self.pizza_page(pizzas, stage, pizza), text="  피자 %d  " % number)
        if len(form["pizzas"]) > 1:
            tk.Button(bar, text="지금 보는 피자 삭제", command=lambda: self.remove_pizza(stage)).pack(side="left")
        pizzas.select(sheet.get("selected", 0) if sheet.get("selected", 0) < len(form["pizzas"]) else 0)

    def pizza_page(self, parent, stage, pizza):
        tk = self.tk
        outer = tk.Frame(parent, bg=PAPER)
        canvas = tk.Canvas(outer, bg=PAPER, highlightthickness=0)
        scroll = self.ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        page = tk.Frame(canvas, bg=PAPER, padx=10, pady=8)
        window = canvas.create_window(0, 0, window=page, anchor="nw")
        page.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        # The wheel scrolls whichever pizza page the mouse is over.
        wheel = lambda event: canvas.yview_scroll(-int(event.delta / 120), "units")
        outer.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", wheel))
        outer.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

        whole = tk.LabelFrame(page, text="피자 전체", bg=PAPER, fg=INK, font=(FONT, 10, "bold"), padx=6, pady=4)
        whole.pack(fill="x")
        grid = tk.Frame(whole, bg=PAPER)
        grid.pack(fill="x")
        self.option_grid(grid, self.data["pizza_options"], pizza, 8, font=(FONT, 10),
                         special={"half_and_half": lambda value: self.set_half(stage, pizza, value)})
        sides = tk.Frame(page, bg=PAPER)
        sides.pack(fill="both", expand=True, pady=(6, 0))
        columns = 6 if len(pizza["sides"]) == 1 else 3
        for number, side in enumerate(pizza["sides"], 1):
            title = "재료" if len(pizza["sides"]) == 1 else ("반쪽 %d" % number)
            box = tk.LabelFrame(sides, text=title, bg=PAPER, fg=INK, font=(FONT, 10, "bold"), padx=6, pady=4)
            box.pack(side="left", fill="both", expand=True, padx=(0, 6))
            for group_title, options in self.data["side_groups"]:
                tk.Label(box, text=group_title, bg=PAPER, fg=MUTED, font=(FONT, 9, "bold"), anchor="w").pack(fill="x", pady=(5, 0))
                grid = tk.Frame(box, bg=PAPER)
                grid.pack(fill="x")
                self.option_grid(grid, options, side, columns, font=(FONT, 9))
        return outer

    def option_grid(self, grid, options, target, columns, font, special=None):
        """Check boxes in columns; a single-choice group gets its own row of radio buttons."""
        tk = self.tk
        choices = {key: choice for choice in self.data.get("single_choices", []) for key in choice["keys"]}
        labels = dict(options)
        row = column = 0
        shown = set()
        for key, label in options:
            if key in shown:
                continue
            choice = choices.get(key)
            if choice:
                if column:
                    row, column = row + 1, 0
                keys = [k for k in choice["keys"] if k in labels]
                shown.update(keys)
                line = tk.Frame(grid, bg=PAPER)
                line.grid(row=row, column=0, columnspan=columns, sticky="w", pady=1)
                tk.Label(line, text=choice["title"], bg=PAPER, fg=INK, font=font).pack(side="left", padx=(0, 6))
                var = tk.StringVar(value=next((k for k in keys if target[k]), ""))
                self.keep[self.drawing].append(var)

                def pick(var=var, keys=keys):
                    for k in keys:
                        target[k] = k == var.get()
                for value, text in [("", choice["default"])] + [(k, labels[k]) for k in keys]:
                    tk.Radiobutton(line, text=text, value=value, variable=var, command=pick, tristatevalue=NOT_CHOSEN,
                                   bg=PAPER, font=font).pack(side="left", padx=2)
                row += 1
                continue
            var = tk.BooleanVar(value=target[key])
            self.keep[self.drawing].append(var)
            if special and key in special:
                command = lambda v=var, k=key: special[k](v.get())
            else:
                command = lambda k=key, v=var: target.__setitem__(k, v.get())
            tk.Checkbutton(grid, text=label, variable=var, command=command, bg=PAPER, anchor="w",
                           font=font).grid(row=row, column=column, sticky="w", padx=(0, 4))
            column += 1
            if column == columns:
                row, column = row + 1, 0

    def add_pizza(self, stage):
        form = self.sheets[stage]["form"]
        form["pizzas"].append(empty_pizza(self.data))
        self.sheets[stage]["selected"] = len(form["pizzas"]) - 1
        self.draw(stage)

    def remove_pizza(self, stage):
        sheet = self.sheets[stage]
        current = sheet["pizzas"].index("current")
        if len(sheet["form"]["pizzas"]) > 1:
            sheet["form"]["pizzas"].pop(current)
            sheet["selected"] = 0
            self.draw(stage)

    def set_half(self, stage, pizza, value):
        pizza["half_and_half"] = value
        if value and len(pizza["sides"]) == 1:
            pizza["sides"].append(deepcopy(pizza["sides"][0]))
        elif not value:
            pizza["sides"] = pizza["sides"][:1]
        self.sheets[stage]["selected"] = self.sheets[stage]["form"]["pizzas"].index(pizza)
        self.draw(stage)

    def show_guide(self):
        from tkinter import messagebox
        messagebox.showinfo("작성 안내", self.data["guide"], parent=self.root)


def main():
    if EMBEDDED is None:
        print("이 파일은 원본입니다. scripts/build_l_annotator.py로 배포 파일을 만들어 실행하세요.")
        return 1
    try:
        import tkinter as tk
    except ImportError:
        print("tkinter가 없는 Python입니다. python.org에서 Python을 설치해 주세요.")
        return 1
    root = tk.Tk()
    app = App(root, EMBEDDED)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
