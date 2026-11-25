"""Model runs, Q-SLATE data and results for the kitchen window.

The kitchen stays on the Tk thread: a model run waits for each API reply on a worker
thread, then hands the tool call to the window, which executes it on the shown kitchen
and redraws. A whole-set run uses the batch engine without drawing and reports progress.
"""

from datetime import datetime
import json
from pathlib import Path
import queue
import threading
import webbrowser

from . import ai_runner
from .credentials import KEY_FILE, CredentialError, load_api_keys
from .game_cli import ToolEnvironment
from .kitchen import observable_state
from .game_orders import PRACTICE
from .providers import RequestPacer, create_session, list_models


ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
TERMINATION_LABELS = {"finished": "완료", "api_error": "API 오류", "request_limit": "요청 한도",
                      "tool_limit": "도구 한도", "time_limit": "시간 한도", "tool_error_limit": "도구 오류 반복",
                      "cost_limit": "비용 한도", "cancelled": "중지", "not_run": "미실행"}
PRACTICE_IDS = {order["id"] for order in PRACTICE}
GUI_PROVIDERS = ("gemini", "openai", "anthropic", "mistral", "vllm")


def model_choices(provider, config):
    """Models listed in the config for this service; the box also accepts any typed ID."""
    if provider == "vllm":
        return list((config.get("local_models") or {}).get("models") or {})
    names = list((config.get("pricing") or {}).get(provider) or {})
    default = (config.get("default_models") or {}).get(provider)
    if default in names:
        names.remove(default)
    return ([default] if default else []) + names


def read_records(path):
    """Full Q-SLATE records by ID, for the data window; the kitchen only loads Q, A and S."""
    records = {}
    if path and Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                record = json.loads(line)
                records[record["id"]] = record
    return records


class Panels:
    def __init__(self, window, parent, *, data_path=None, key_file=KEY_FILE):
        tk, ttk = window.tk, window.ttk
        self.window, self.tk, self.ttk = window, tk, ttk
        self.data_path = Path(data_path) if data_path else None
        self.key_file = Path(key_file)
        self.config = ai_runner.load_config()
        self.records = read_records(self.data_path)
        self.results = []
        self.runs = {}
        self.batch_folder = None
        self.running = False
        self.stop = threading.Event()
        self.inbox = queue.Queue()
        self.slate_window = self.results_window = None

        frame = tk.Frame(parent, bg=window.PAPER, padx=14, pady=4)
        frame.pack(fill="x", padx=18, pady=(8, 0))
        rows = [tk.Frame(frame, bg=window.PAPER), tk.Frame(frame, bg=window.PAPER)]
        rows[0].pack(fill="x", pady=(2, 3))
        rows[1].pack(fill="x", pady=(3, 2))

        def label(row, text, **pack):
            tk.Label(row, text=text, bg=window.PAPER, fg=window.MUTED, font=(window.FONT, 9)).pack(side="left", **pack)

        # Row 1: which case, how many, and the data windows.
        bar = rows[0]
        label(bar, "문항")
        window.order_var = tk.StringVar()
        window.selector = ttk.Combobox(bar, textvariable=window.order_var, values=list(window.labels),
                                       state="readonly", width=30)
        window.selector.pack(side="left", padx=(4, 12))
        window.selector.bind("<<ComboboxSelected>>",
                             lambda _: window.choose_case(window.labels[window.order_var.get()]))
        self.scope_var = tk.StringVar(value="current")
        for text, value in (("현재 문항", "current"), (f"전체 문항 {len(self.batch_cases())}개", "all")):
            tk.Radiobutton(bar, text=text, variable=self.scope_var, value=value, bg=window.PAPER,
                           activebackground=window.PAPER, fg=window.INK, font=(window.FONT, 9)).pack(side="left")
        window.button(bar, "채점 결과", self.show_results, bg="#e8deca", fg=window.INK, padx=8, pady=3).pack(side="right")
        window.button(bar, "SLATE 데이터", self.show_slate, bg="#e8deca", fg=window.INK, padx=8, pady=3).pack(side="right", padx=4)

        # Row 2: the model and its budget, then run and stop.
        bar = rows[1]
        label(bar, "AI 서비스")
        self.provider_var = tk.StringVar(value="anthropic")
        provider = ttk.Combobox(bar, textvariable=self.provider_var, values=list(GUI_PROVIDERS), state="readonly", width=10)
        provider.pack(side="left", padx=(4, 10))
        provider.bind("<<ComboboxSelected>>", lambda _: self.provider_changed())
        label(bar, "모델")
        self.model_var = tk.StringVar()
        self.model_box = ttk.Combobox(bar, textvariable=self.model_var, width=26)
        self.model_box.pack(side="left", padx=(4, 4))
        window.button(bar, "목록", self.fetch_models, bg="#eee4cf", fg=window.INK, padx=6, pady=3).pack(side="left")
        self.key_var = tk.StringVar()
        tk.Label(bar, textvariable=self.key_var, bg=window.PAPER, fg=window.MUTED,
                 font=(window.FONT, 9)).pack(side="left", padx=(8, 12))
        label(bar, "사고 수준")
        self.effort_var = tk.StringVar(value="medium")
        ttk.Combobox(bar, textvariable=self.effort_var, values=["기본값", "low", "medium", "high"],
                     state="readonly", width=7).pack(side="left", padx=(4, 0))
        label(bar, "비용 한도 $", padx=(10, 0))
        self.budget_var = tk.StringVar(value="1.00")
        self.budget_entry = tk.Entry(bar, textvariable=self.budget_var, width=6)
        self.budget_entry.pack(side="left", padx=(2, 10))
        self.run_button = window.button(bar, "AI 실행", self.start, padx=10, pady=3)
        self.run_button.pack(side="left")
        self.stop_button = window.button(bar, "중지", self.request_stop, bg=window.RED, padx=10, pady=3)
        self.stop_button.pack(side="left", padx=(4, 0))
        self.provider_changed()
        self.update_buttons()
        window.root.after(40, self.poll)

    # ----- Tk-thread plumbing -------------------------------------------------
    def poll(self):
        if self.window.closed:
            return
        while True:
            try:
                job = self.inbox.get_nowait()
            except queue.Empty:
                break
            job()
        self.window.root.after(40, self.poll)

    def later(self, job):
        """Run on the Tk thread without waiting."""
        self.inbox.put(job)

    def on_main(self, job):
        """Run on the Tk thread and return its value to the worker."""
        done, box = threading.Event(), {}

        def run():
            try:
                box["value"] = job()
            except Exception as exc:  # returned to the worker, which decides how to stop
                box["error"] = exc
            finally:
                done.set()
        self.inbox.put(run)
        while not done.wait(0.1):
            if self.window.closed:
                raise RuntimeError("창이 닫혔습니다")
        if "error" in box:
            raise box["error"]
        return box["value"]

    # ----- settings -----------------------------------------------------------
    def provider_changed(self):
        provider = self.provider_var.get()
        choices = model_choices(provider, self.config)
        self.model_box.configure(values=choices)
        self.model_var.set(choices[0] if choices else "")
        try:
            present = bool(load_api_keys(self.key_file)[provider])
        except CredentialError:
            present = False
        self.key_var.set("키 필요 없음" if provider == "vllm" else ("키 확인됨" if present else "키 없음"))
        # Local models have no token price, so their budget is the request and tool limits.
        self.budget_entry.configure(state="disabled" if provider == "vllm" else "normal")

    def session_args(self):
        provider, model = self.provider_var.get(), self.model_var.get().strip()
        if not model:
            raise ValueError("모델을 선택하세요.")
        keys = load_api_keys(self.key_file, required=[] if provider == "vllm" else [provider])
        options = ai_runner.session_options_for(provider, model, self.config)
        if self.effort_var.get() != "기본값" and provider != "vllm":
            options["reasoning_effort"] = self.effort_var.get()
        return provider, model, keys[provider], options

    def budget(self, provider, model):
        if provider == "vllm" or not ai_runner.model_price(provider, model, self.config):
            return None
        value = float(self.budget_var.get())
        if value <= 0:
            raise ValueError("비용 한도는 0보다 커야 합니다.")
        return value

    def fetch_models(self):
        provider = self.provider_var.get()

        def work():
            try:
                key = "" if provider == "vllm" else load_api_keys(self.key_file, required=[provider])[provider]
                base = ai_runner.session_options_for(provider, "", self.config).get("base_url")
                names = list_models(provider, key, base_url=base) if provider == "vllm" else list_models(provider, key)
                self.later(lambda: (self.model_box.configure(values=names),
                                    self.window.status_var.set(f"{provider} 모델 {len(names)}개를 불러왔습니다.")))
            except Exception as exc:
                message = "모델 목록을 불러오지 못했습니다: " + str(exc)
                self.later(lambda: self.window.status_var.set(message))
        threading.Thread(target=work, daemon=True).start()

    def batch_cases(self):
        return [order for order in self.window.orders.values() if order["id"] not in PRACTICE_IDS]

    def update_buttons(self):
        self.run_button.configure(state="disabled" if self.running else "normal")
        self.stop_button.configure(state="normal" if self.running else "disabled")

    # ----- runs ---------------------------------------------------------------
    def start(self):
        if self.running:
            return
        try:
            provider, model, key, options = self.session_args()
            budget = self.budget(provider, model)
        except (CredentialError, ValueError) as exc:
            self.window.status_var.set(str(exc))
            return
        self.stop.clear()
        self.running = True
        self.window.ai_running = True
        self.update_buttons()
        if self.scope_var.get() == "current":
            self.start_case(provider, model, key, options, budget)
        else:
            self.start_batch(provider, model, key, options, budget)

    def request_stop(self):
        self.stop.set()
        self.window.status_var.set("중지를 요청했습니다. 진행 중인 요청이 끝나면 멈춥니다.")

    def finish_run(self, message):
        self.running = False
        self.window.ai_running = False
        self.update_buttons()
        self.window.status_var.set(message)
        self.window.refresh()

    def start_case(self, provider, model, key, options, budget):
        window = self.window
        order = window.session.order
        environment = ToolEnvironment(order, oven_seconds=window.oven_seconds)
        window.use_session(environment.session)
        window.status_var.set(f"{model}이(가) {order['id']}을(를) 진행 중입니다.")

        def execute(text):
            return self.on_main(lambda: window.apply_model_call(environment, text))

        def work():
            session = None
            try:
                session = create_session(provider, key, model, pacer=RequestPacer(3), stop=self.stop, **options)
                label = f"{provider} {model}"
                live = lambda event: self.later(lambda: self.remember_run(order["id"], label, event["turns"]))
                result = ai_runner.run_agent(order, session, environment=environment, execute=execute,
                                             stop=self.stop, max_cost_usd=budget, config=self.config,
                                             oven_seconds=window.oven_seconds, on_event=live)
                path = self.save_single(result)
                self.later(lambda: self.case_done(result, path))
            except Exception as exc:
                message = "AI 실행을 시작하지 못했습니다: " + str(exc)
                self.later(lambda: self.finish_run(message))
            finally:
                if session:
                    session.close()
        threading.Thread(target=work, daemon=True).start()

    def save_single(self, result):
        folder = RESULTS / "gui"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = folder / f"{stamp}_{result['case_id']}_{result['provider']}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def case_done(self, result, path):
        self.remember_run(result["case_id"], f"{result['provider']} {result['model']}", result.get("turns") or [], result)
        summary = ai_runner.summarise(result)
        self.add_result("모델", result["case_id"], summary["model"], summary["passed"],
                        summary["requests"], summary["cost_usd"], result.get("evaluation"),
                        TERMINATION_LABELS.get(result["termination"], result["termination"]), path)
        self.window.show_outcome(result.get("evaluation"), result["termination"])
        cost = "" if summary["cost_usd"] is None else f", 추정 비용 ${summary['cost_usd']:.4f}"
        self.finish_run(f"AI 실행 종료: {TERMINATION_LABELS.get(result['termination'], result['termination'])}, "
                        f"요청 {summary['requests']}회{cost}. 기록: {path.name}")

    def start_batch(self, provider, model, key, options, budget):
        from .batch_engine import run_batch

        cases = self.batch_cases()
        folder = RESULTS / datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
        self.window.status_var.set(f"전체 {len(cases)}문항의 예상 비용을 계산하고 있습니다.")

        class Offline:
            """Offline estimate: no request is sent, so unknown token densities use the fallback ratio."""
            def __init__(self):
                self.provider, self.model = provider, model

            def count_tokens(self, prompt, tools):
                raise RuntimeError("offline")

        def work():
            try:
                low = high = 0.0
                priced = bool(ai_runner.model_price(provider, model, self.config))
                for case in cases:
                    if self.stop.is_set():
                        break
                    report = ai_runner.estimate_session(case, Offline(), config=self.config)
                    low += report["optimistic"].get("total_usd") or 0
                    high += report["conservative"].get("total_usd") or 0
                if self.stop.is_set() or not self.on_main(lambda: self.confirm_batch(len(cases), priced, low, high, budget)):
                    self.later(lambda: self.finish_run("전체 문항 실행을 취소했습니다."))
                    return

                def progress(event):
                    if event["kind"] == "batch_progress":
                        report, summary = event["report"], event["summary"]
                        if not event["preserved"]:
                            self.later(lambda: self.remember_run(report["case_id"], f"{provider} {model}",
                                                                 report.get("turns") or [], report))
                        text = (f"[{event['index']}/{event['total']}] {event['case_id']} "
                                f"{TERMINATION_LABELS.get(report['termination'], report['termination'])}, "
                                f"통과 {summary['passed']}/{summary['attempted']}, "
                                f"누적 ${summary.get('cumulative_cost_usd', 0):.4f}")
                        self.later(lambda: self.window.status_var.set(text))
                result = run_batch(cases, provider, model, key, folder, max_total_cost_usd=budget,
                                   session_options=options, stop=self.stop, on_event=progress, config=self.config,
                                   session_factory=create_session,
                                   environment_options={"oven_seconds": self.window.oven_seconds})
                self.batch_folder = folder
                summary = result["summary"]
                self.later(lambda: (self.finish_run(
                    f"전체 문항 실행 종료: 통과 {summary['passed']}/{summary['attempted']}, "
                    f"중단 이유 {summary.get('batch_stop_reason') or '없음'}, 추정 비용 ${summary.get('cumulative_cost_usd', 0):.4f}"),
                    self.show_results()))
            except Exception as exc:
                message = "전체 문항 실행 오류: " + str(exc)
                self.later(lambda: self.finish_run(message))
        threading.Thread(target=work, daemon=True).start()

    def confirm_batch(self, count, priced, low, high, budget):
        from tkinter import messagebox
        if priced:
            text = (f"{count}개 문항을 실행합니다.\n예상 비용: 낙관 ${low:.2f}, 보수 ${high:.2f}\n"
                    f"비용 한도 ${budget:.2f}에 이르면 다음 문항을 시작하지 않습니다.\n\n계속할까요?")
        else:
            text = f"{count}개 문항을 실행합니다. 이 모델은 단가가 없어 비용 한도 없이 요청 수와 도구 호출 수로 제한합니다.\n\n계속할까요?"
        return messagebox.askyesno("전체 문항 실행", text, parent=self.window.root)

    # ----- results ------------------------------------------------------------
    def add_result(self, actor, case_id, model, passed, requests, cost, evaluation, status, path=None):
        self.results.append({"time": datetime.now().strftime("%H:%M:%S"), "actor": actor, "case_id": case_id,
                             "model": model, "passed": passed, "requests": requests,
                             "cost": cost, "status": status, "evaluation": evaluation, "path": path})
        if self.results_window is not None and self.results_window.winfo_exists():
            self.fill_results()

    def record_human(self, report):
        evaluation = report.get("evaluation") or {}
        self.add_result("사람", report["case_id"], "", (report.get("score") or {}).get("passed"),
                        None, None, evaluation, "완료")

    def show_results(self):
        tk, ttk = self.tk, self.ttk
        if self.results_window is not None and self.results_window.winfo_exists():
            self.results_window.lift()
            self.fill_results()
            return
        top = self.results_window = tk.Toplevel(self.window.root)
        top.title("채점 결과")
        top.geometry("980x560")
        columns = ("time", "actor", "case", "model", "passed", "requests", "cost", "status")
        heads = ("시각", "수행", "문항", "모델", "주문 조건", "요청", "추정 비용", "종료")
        self.table = ttk.Treeview(top, columns=columns, show="headings", height=10)
        for column, head, width in zip(columns, heads, (70, 50, 170, 170, 80, 50, 80, 90)):
            self.table.heading(column, text=head)
            self.table.column(column, width=width, anchor="w")
        self.table.pack(fill="x", padx=10, pady=(10, 4))
        self.table.bind("<<TreeviewSelect>>", lambda _: self.show_detail())
        actions = tk.Frame(top)
        actions.pack(fill="x", padx=10)
        tk.Button(actions, text="전체 문항 보고서 열기", command=self.open_report).pack(side="left")
        tk.Button(actions, text="결과 폴더 열기", command=lambda: webbrowser.open(RESULTS.as_uri()) if RESULTS.exists() else None).pack(side="left", padx=6)
        self.batch_var = tk.StringVar()
        tk.Label(actions, textvariable=self.batch_var, anchor="w").pack(side="left", padx=10)
        from tkinter.scrolledtext import ScrolledText
        self.detail = ScrolledText(top, height=16, font=("Consolas", 9))
        self.detail.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.fill_results()

    def fill_results(self):
        self.table.delete(*self.table.get_children())
        for index, row in enumerate(self.results):
            passed = "—" if row["passed"] is None else ("통과" if row["passed"] else "미충족")
            cost = "—" if row["cost"] is None else f"${row['cost']:.4f}"
            self.table.insert("", "end", iid=str(index), values=(row["time"], row["actor"], row["case_id"], row["model"],
                                                                passed, row["requests"] or "—", cost, row["status"]))
        summary_path = self.batch_folder / "summary.json" if self.batch_folder else None
        if summary_path and summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.batch_var.set(f"최근 전체 실행: {summary['model']}, 통과 {summary['passed']}/{summary['attempted']}, "
                               f"추정 ${summary.get('cumulative_cost_usd', 0):.4f}")
        else:
            self.batch_var.set("이번 실행에서 전체 문항을 실행한 기록이 없습니다.")

    def show_detail(self):
        selected = self.table.selection()
        if not selected:
            return
        row = self.results[int(selected[0])]
        self.detail.delete("1.0", "end")
        self.detail.insert("end", json.dumps({"evaluation": row["evaluation"],
                                              "record_file": str(row["path"]) if row["path"] else None},
                                             ensure_ascii=False, indent=2))

    def open_report(self):
        if self.batch_folder and (self.batch_folder / "report.html").exists():
            webbrowser.open((self.batch_folder / "report.html").as_uri())
        else:
            self.window.status_var.set("열 수 있는 전체 문항 보고서가 없습니다.")

    # ----- Q-SLATE data and model output --------------------------------------
    def case_changed(self):
        if self.slate_window is not None and self.slate_window.winfo_exists():
            self.fill_slate()

    def remember_run(self, case_id, label, turns, result=None):
        self.runs[case_id] = {"label": label, "turns": turns, "result": result}
        if self.slate_window is not None and self.slate_window.winfo_exists() \
                and self.window.session.order["id"] == case_id:
            self.fill_model_output()

    def show_slate(self):
        tk, ttk = self.tk, self.ttk
        from tkinter.scrolledtext import ScrolledText
        if self.slate_window is not None and self.slate_window.winfo_exists():
            self.slate_window.lift()
            self.fill_slate()
            return
        top = self.slate_window = tk.Toplevel(self.window.root)
        top.title("SLATE 데이터")
        top.geometry("1100x860")
        self.case_var = tk.StringVar()
        tk.Label(top, textvariable=self.case_var, anchor="w",
                 font=(self.window.FONT, 11, "bold")).pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(top, text="Q 주문", anchor="w", font=(self.window.FONT, 10, "bold")).pack(fill="x", padx=12)
        self.q_text = tk.Text(top, height=3, wrap="word", font=("Consolas", 9), relief="flat")
        self.q_text.pack(fill="x", padx=12, pady=(0, 6))
        panes = ttk.PanedWindow(top, orient="vertical")
        panes.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        model = ttk.LabelFrame(panes, text="모델 출력")
        self.model_head = tk.StringVar()
        tk.Label(model, textvariable=self.model_head, anchor="w", font=(self.window.FONT, 9)).pack(fill="x", padx=6, pady=(4, 0))
        output_tabs = ttk.Notebook(model)
        output_tabs.pack(fill="both", expand=True, padx=4, pady=4)
        self.transcript_text = ScrolledText(output_tabs, font=("Consolas", 9), wrap="word", height=12)
        self.raw_text = ScrolledText(output_tabs, font=("Consolas", 9), wrap="word", height=12)
        output_tabs.add(self.transcript_text, text="진행 과정")
        output_tabs.add(self.raw_text, text="원본 응답 전체")
        panes.add(model, weight=1)

        compare = ttk.LabelFrame(panes, text="SLATE 비교")
        notebook = ttk.Notebook(compare)
        notebook.pack(fill="both", expand=True, padx=4, pady=4)
        self.compare_tabs = {}
        for key, title in (("S", "S 상태"), ("L", "L 언어 분석"), ("A", "A 제작 조건"),
                           ("T", "T 도구 호출"), ("E", "E 실행 결과")):
            frame = ttk.Frame(notebook)
            sides = ttk.PanedWindow(frame, orient="horizontal")
            sides.pack(fill="both", expand=True)
            widgets = []
            for side in ("정답", "모델 출력"):
                box = ttk.Frame(sides)
                tk.Label(box, text=side, anchor="w", font=(self.window.FONT, 10, "bold")).pack(fill="x", padx=4)
                widget = ScrolledText(box, font=("Consolas", 9))
                widget.pack(fill="both", expand=True)
                sides.add(box, weight=1)
                widgets.append(widget)
            notebook.add(frame, text=title)
            self.compare_tabs[key] = widgets
        panes.add(compare, weight=2)
        self.fill_slate()

    @staticmethod
    def put(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.configure(state="disabled")

    @staticmethod
    def dump(value, empty="이 문항에는 해당 데이터가 없습니다."):
        return empty if value is None else json.dumps(value, ensure_ascii=False, indent=2)

    def current_record(self):
        order = self.window.session.order
        return self.records.get(order["id"]) or {"question": order["question"], "answer": order["answer"],
                                                 "state": order.get("state")}

    def fill_slate(self):
        order = self.window.session.order
        record = self.current_record()
        self.case_var.set(f"현재 문항: {order['id']}")
        question = record.get("question") or {}
        self.put(self.q_text, "\n".join(f"{key}: {question.get(key)}" for key in
                                        ("order_text", "clarification_text") if key in question))
        reference = {"S": record.get("state"), "L": record.get("linguistics"), "A": record.get("answer"),
                     "T": record.get("tool_calling"), "E": record.get("reference_evaluation")}
        for key, (left, _) in self.compare_tabs.items():
            self.put(left, self.dump(reference[key]))
        self.fill_model_output()

    def fill_model_output(self):
        run = self.runs.get(self.window.session.order["id"])
        right = {key: widgets[1] for key, widgets in self.compare_tabs.items()}
        if run is None:
            self.model_head.set("이 문항을 모델로 실행한 기록이 없습니다.")
            self.put(self.transcript_text, "")
            self.put(self.raw_text, "")
            for widget in right.values():
                self.put(widget, "")
            return
        result = run.get("result") or {}
        status = ("진행 중" if not result else
                  f"{TERMINATION_LABELS.get(result.get('termination'), result.get('termination'))}, "
                  f"주문 조건 {'통과' if (result.get('score') or {}).get('passed') else '미충족'}")
        cost = (result.get("cost") or {}).get("total_usd")
        self.model_head.set(f"{run['label']}: {status}, 요청 {len(run['turns'])}회"
                            + ("" if cost is None else f", 추정 비용 ${cost:.4f}"))
        self.put(self.transcript_text, self.transcript(run["turns"]))
        self.put(self.raw_text, "\n\n".join(
            f"[요청 {turn['request']}]\n" + json.dumps(turn.get("raw_reply"), ensure_ascii=False, indent=2)
            for turn in run["turns"]))
        calls = [{"tool": c["tool"], "args": c["args"]} for turn in run["turns"] for c in turn["calls"]]
        self.put(right["T"], json.dumps(calls, ensure_ascii=False, indent=2))
        for key in ("L", "A"):
            self.put(right[key], f"현재 실행 방식은 모델이 주문을 읽고 곧바로 도구를 호출하므로 {key}를 따로 출력하지 않습니다.\n"
                                 f"모델이 {key}를 쓰는 단계별 평가는 아직 구현되지 않았습니다.")
        if not result:
            for key in ("S", "E"):
                self.put(right[key], "실행이 끝나면 표시됩니다.")
            return
        final = observable_state((result.get("execution") or {}).get("final_state")) or {}
        self.put(right["S"], "모델이 시작한 초기 상태입니다. 정답 S와 같아야 합니다.\n\n"
                 + self.dump(observable_state(result.get("state"))))
        self.put(right["E"], self.dump({"evaluation": result.get("evaluation"), "final_state": final}))

    @staticmethod
    def transcript(turns):
        lines = []
        for turn in turns:
            usage = turn.get("usage") or {}
            lines.append(f"[요청 {turn['request']}] 입력 {usage.get('input') or 0:,}, 출력 {usage.get('output') or 0:,} 토큰")
            if turn.get("reasoning"):
                lines.append("사고 전체:" if turn.get("reasoning_scope") == "full" else "사고 요약 (서비스가 제공하는 요약):")
                lines.extend("  " + line for line in turn["reasoning"].splitlines())
            if turn.get("text"):
                lines.append("모델의 글:")
                lines.extend("  " + line for line in turn["text"].splitlines())
            if not turn.get("reasoning") and not turn.get("text") and not turn.get("calls"):
                lines.append("  (빈 응답)")
            for call in turn.get("calls", []):
                response = call.get("response") or {}
                outcome = "성공" if response.get("ok") else "오류: " + str(response.get("error"))
                lines.append(f"  {call['tool']} {json.dumps(call['args'], ensure_ascii=False)} -> {outcome}")
            lines.append("")
        return "\n".join(lines)
