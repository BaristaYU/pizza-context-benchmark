from types import SimpleNamespace
import unittest

from pizzabench.game import GameWindow
from pizzabench.game_orders import load_orders


class GameGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
        except ImportError as exc:
            raise unittest.SkipTest(f"Tk unavailable: {exc}")
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk display unavailable: {exc}")
        cls.root.withdraw()
        cls.errors = []
        cls.root.report_callback_exception = lambda *args: cls.errors.append(args)
        cls.game = GameWindow(cls.root, load_orders(), oven_seconds=.5)
        cls.root.update_idletasks()

    @classmethod
    def tearDownClass(cls):
        cls.game.close()

    def setUp(self):
        self.game.select_case("practice_olive")
        self.root.update_idletasks()

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def event(self, x, y):
        cx, cy, radius = self.game.geometry()
        return SimpleNamespace(x=cx+x*radius, y=cy+y*radius)

    def stroke(self, start, end):
        self.game.on_press(self.event(*start))
        self.game.on_drag(self.event(*end))
        self.game.on_release(self.event(*end))

    def test_mouse_gameplay_to_success_without_reference_plan(self):
        g = self.game
        g.create("regular")
        g.on_press(self.event(0, 0))
        for item, kind in [("sauce", "tomato"), ("cheese", None)]:
            g.choose_tool(item, kind)
            self.stroke((-.6, 0), (.6, 0))
        self.assertEqual(sum(r["tool"] == "paint" for r in g.kitchen.trace), 2)
        g.choose_tool("topping", "olive")
        self.stroke((-.25, .3), (-.25, .3))
        g.act("bake")
        g.choose_tool("cutter", None)
        self.stroke((-.9, 0), (.9, 0))
        self.stroke((0, -.9), (0, .9))
        self.stroke((-.65, -.65), (.65, .65))
        self.assertEqual(g.kitchen.pizzas[1].snapshot()["cuts"], 6)
        g.act("serve")
        g.deliver()
        self.assertTrue(g.session.score["passed"])
        self.assertIn("주문 성공", g.result_var.get())
        self.assertNotIn("quality", g.session.evaluation)
        self.assertFalse(hasattr(g, "plan"))
        self.assertTrue(g.canvas.find_all())

    def test_menu_window_lists_recipes_and_categories(self):
        self.game.show_menu()
        text = self.game.menu_text.get("1.0", "end")
        self.assertIn("Hawaiian", text)
        self.assertIn("stinky", text)
        self.game.menu_text.winfo_toplevel().destroy()

    def test_drag_places_several_toppings_in_one_call(self):
        g = self.game
        g.create("regular")
        g.act("spread")
        g.choose_tool("topping", "olive")
        g.on_press(self.event(-.6, 0))
        for x in (-.4, -.2, 0, .2, .4):
            g.on_drag(self.event(x, 0))
        g.on_release(self.event(.4, 0))
        calls = [r for r in g.kitchen.trace if r["tool"] == "place_toppings"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]["args"]["points"]), 6)
        self.assertEqual(len(g.kitchen.pizzas[1].pieces), 6)

    def test_reset_clears_revealed_text_pizzas_results_and_selection(self):
        g = self.game
        g.clarify()
        self.assertTrue(g.session.clarified)
        g.create("wheat")
        g.result_var.set("old score")
        g.reset()
        self.assertFalse(g.session.clarified)
        self.assertEqual(g.clarification_var.get(), "")
        self.assertEqual(g.result_var.get(), "")
        self.assertIsNone(g.selected)
        self.assertEqual(g.kitchen.snapshot()["pizza_count"], 0)
        self.assertEqual(g.kitchen.trace, [])

    def test_half_fill_and_undo_use_the_same_backend(self):
        g = self.game
        g.create("regular")
        g.act("spread")
        g.choose_tool("sauce", "pesto")
        g.region_var.set("left")
        g.fill_region()
        self.assertEqual(g.kitchen.pizzas[1].snapshot()["sauce_placement"], {"pesto": "left"})
        g.act("undo")
        self.assertEqual(g.kitchen.pizzas[1].snapshot()["sauce"], [])

    def test_score_label_grows_to_keep_both_result_lines_visible(self):
        from tkinter.font import Font
        g = self.game
        g.result_var.set("주문 미완료\n종료 이유: 요청 한도")
        self.root.update_idletasks()
        text = Font(root=self.root,font=g.result_label.cget("font"))
        self.assertGreaterEqual(g.result_label.winfo_reqheight(),2*text.metrics("linespace"))


if __name__ == "__main__":
    unittest.main()
