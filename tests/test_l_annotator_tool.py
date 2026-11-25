import importlib.machinery
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(folder):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_l_annotator
    output, archive = build_l_annotator.build(Path(folder) / "L_annotator")
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("l_annotator_built", str(output / "L_annotator.pyw"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return output, archive, module


class ToolTests(unittest.TestCase):
    def test_package_is_self_contained_in_the_fixed_order_without_difficulty(self):
        with tempfile.TemporaryDirectory() as folder:
            output, archive, module = build(folder)
            self.assertTrue(archive.exists())
            data = module.EMBEDDED
            text = (output / "L_annotator.pyw").read_text(encoding="utf-8")
            self.assertNotIn("pizzabench", text.replace("scripts/build_l_annotator.py", ""))
            self.assertNotIn('"difficulty"', json.dumps(data["questions"]))
            self.assertEqual([q["id"] for q in data["questions"]], ["en100_%03d" % n for n in range(1, 101)])
            self.assertEqual([q["number"] for q in data["questions"]], list(range(1, 101)))

    def test_flow_saves_both_sheets_and_difficulty_then_resumes(self):
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as exc:
            raise unittest.SkipTest(f"Tk unavailable: {exc}")
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as folder:
                _, _, module = build(folder)
                app = module.App(root, module.EMBEDDED, folder=folder)
                app.name_var.set("tester")
                app.start()
                self.assertEqual(app.difficulty_vars["initial"].get(), "")
                self.assertEqual(app.difficulty_buttons["initial"][0].cget("tristatevalue"), module.NOT_CHOSEN)
                app.save_next()
                self.assertIn("네?", app.status_var.get())
                app.sheets["initial"]["form"]["pizzas"][0]["sides"][0]["pepperoni"] = True
                app.hear_again()
                self.assertTrue(app.sheets["clarified"]["form"]["pizzas"][0]["sides"][0]["pepperoni"])
                app.set_half("clarified", app.sheets["clarified"]["form"]["pizzas"][0], True)
                app.save_next()
                self.assertIn("①", app.status_var.get())
                app.difficulty_vars["initial"].set("상")
                app.save_next()
                self.assertIn("②", app.status_var.get())
                app.difficulty_vars["clarified"].set("하")
                app.save_next()
                path = Path(folder) / "L_결과_tester.json"
                saved = json.loads(path.read_text(encoding="utf-8"))
                first, second, third = (q["id"] for q in module.EMBEDDED["questions"][:3])
                answer = saved["answers"][first]
                self.assertEqual(answer["difficulty"], {"initial": "상", "clarified": "하"})
                self.assertTrue(answer["clarified"]["pizzas"][0]["half_and_half"])
                self.assertEqual(saved["drafts"], {})
                self.assertEqual(app.index, 1)

                # Leaving an untouched case writes nothing; leaving edited work keeps it as a draft.
                app.go(2)
                self.assertNotIn(second, json.loads(path.read_text(encoding="utf-8"))["drafts"])
                app.sheets["initial"]["form"]["pizzas"][0]["sides"][0]["olive"] = True
                app.difficulty_vars["initial"].set("중")
                app.close = lambda: app.stash()
                app.close()
                draft = json.loads(path.read_text(encoding="utf-8"))["drafts"][third]
                self.assertTrue(draft["initial"]["pizzas"][0]["sides"][0]["olive"])

                again = module.App(root, module.EMBEDDED, folder=folder)
                again.name_var.set("tester")
                again.start()
                self.assertEqual(again.index, 2)
                self.assertIn("불러왔습니다", again.status_var.get())
                self.assertEqual(again.difficulty_vars["initial"].get(), "중")
                self.assertIn("작성 중", again.case_box.cget("values")[2])
                again.go(0)
                self.assertEqual(again.difficulty_vars["clarified"].get(), "하")
                self.assertTrue(again.heard_again)
                self.assertIn("완료 1 / 100", again.progress_var.get())

                # Reworking a finished case without saving takes it out of the finished count.
                again.difficulty_vars["clarified"].set("중")
                again.go(1)
                self.assertIn("완료 0 / 100", again.progress_var.get())
                self.assertIn("작성 중", again.case_box.cget("values")[0])
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
