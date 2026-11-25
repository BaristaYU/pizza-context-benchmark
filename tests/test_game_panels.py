import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from pizzabench import game_panels
from pizzabench.ai_runner import reference_plan_for
from pizzabench.game import GameWindow
from pizzabench.game_cli import ToolEnvironment
from pizzabench.game_orders import load_orders


class Scripted:
    """Stands in for a provider: plays the reference plan, a few calls per reply."""

    provider, settings = "anthropic", {"provider": "Scripted"}

    def __init__(self, provider, key, model, **_):
        self.model, self.queue = model, None

    def ask(self, prompt, tools):
        if self.queue is None:
            text = json.loads(prompt)["observation"]["question"]["order_text"]
            order = next(o for o in load_orders() if o["question"]["order_text"] == text)
            self.queue = reference_plan_for(order, ToolEnvironment(order).session.kitchen.snapshot())
            self.queue.append({"tool": "finish", "args": {}})
        actions, self.queue = self.queue[:5], self.queue[5:]
        return actions, {"input": 1000, "output": 20, "total": 1020}

    def reply(self, results, idle=None):
        pass

    def close(self):
        pass


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
            cls.root = tk.Tk()
        except Exception as exc:
            raise unittest.SkipTest(f"Tk display unavailable: {exc}")
        cls.root.withdraw()
        cls.errors = []
        cls.root.report_callback_exception = lambda *args: cls.errors.append(args)
        cls.folder = tempfile.TemporaryDirectory()
        cls.patches = [mock.patch.object(game_panels, "RESULTS", Path(cls.folder.name)),
                       mock.patch.object(game_panels, "create_session", Scripted),
                       mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-panel"}, clear=False)]
        for patch in cls.patches:
            patch.start()
        cls.game = GameWindow(cls.root, load_orders(), oven_seconds=.5)
        cls.root.update_idletasks()

    @classmethod
    def tearDownClass(cls):
        cls.game.close()
        for patch in cls.patches:
            patch.stop()
        cls.folder.cleanup()

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def wait(self, seconds=60):
        deadline = time.monotonic() + seconds
        while self.game.panels.running and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.game.panels.running, "run did not finish")

    def start(self, scope):
        panels = self.game.panels
        panels.provider_var.set("anthropic")
        panels.provider_changed()
        panels.model_var.set("claude-haiku-5-5")
        panels.scope_var.set(scope)
        with mock.patch("pizzabench.providers.RequestPacer.wait"):
            panels.start()
            self.assertTrue(self.game.ai_running)
            self.wait()

    def test_header_and_buttons_carry_no_order_hints(self):
        texts = []
        def collect(widget):
            try:
                texts.append(str(widget.cget("text")))
            except Exception:
                pass
            for child in widget.winfo_children():
                collect(child)
        collect(self.root)
        self.assertIn("Pizza Context Benchmark", texts)
        self.assertFalse([t for t in texts if t and t[0] in "①②③④"])
        self.assertNotIn("주문을 읽고, 직접 만들어 보세요", texts)

    def test_model_plays_the_shown_kitchen_and_reports_result(self):
        self.game.select_case("en100_001")
        self.start("current")
        game = self.game
        self.assertTrue(game.kitchen.snapshot()["submitted"])
        self.assertIn("주문 성공", game.result_var.get())
        row = game.panels.results[-1]
        self.assertEqual((row["actor"], row["case_id"], row["passed"]), ("모델", "en100_001", True))
        self.assertTrue(Path(row["path"]).exists())
        game.panels.show_slate()
        self.root.update()
        self.assertIn("통과", game.panels.model_head.get())
        self.assertIn("[요청 1]", game.panels.transcript_text.get("1.0", "end"))
        reference, model = game.panels.compare_tabs["T"]
        self.assertIn('"tool": "create"', model.get("1.0", "end"))
        self.assertIn("구현되지 않았습니다", game.panels.compare_tabs["A"][1].get("1.0", "end"))
        game.panels.slate_window.destroy()
        self.assertNotIn("sk-panel", Path(row["path"]).read_text(encoding="utf-8"))
        game.panels.show_results()
        self.root.update()
        self.assertEqual(len(game.panels.table.get_children()), len(game.panels.results))

    def test_manual_actions_are_blocked_while_a_model_plays(self):
        game = self.game
        game.ai_running = True
        try:
            game.create("regular")
            self.assertEqual(game.kitchen.snapshot()["pizza_count"], 0)
            self.assertIn("AI 실행 중", game.status_var.get())
        finally:
            game.ai_running = False

    def test_whole_set_runs_through_the_batch_engine(self):
        with mock.patch.object(game_panels.Panels, "confirm_batch", return_value=True):
            self.start("all")
        panels = self.game.panels
        summary = json.loads((panels.batch_folder / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["attempted"], len(panels.batch_cases()))
        self.assertEqual(summary["passed"], summary["attempted"])
        self.assertTrue((panels.batch_folder / "report.html").exists())

    def test_slate_window_shows_dataset_and_current_case(self):
        self.game.select_case("en100_002")
        self.game.panels.show_slate()
        self.root.update()
        panels = self.game.panels
        self.assertTrue(panels.slate_window.winfo_exists())
        self.assertEqual(panels.case_var.get(), "현재 문항: en100_002")
        self.assertIn("order_text", panels.q_text.get("1.0", "end"))
        self.assertIn("기록이 없습니다", panels.model_head.get())
        panels.slate_window.destroy()


if __name__ == "__main__":
    unittest.main()
