import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pizzabench.linguistics_form import from_ticks

ROOT = Path(__file__).resolve().parents[1]


class CompareScriptTests(unittest.TestCase):
    def test_report_lists_agreement_differences_and_difficulty(self):
        case = json.loads((ROOT / "data/english100/benchmark_cases.jsonl").read_text(encoding="utf-8").splitlines()[0])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "L_결과_alice.json"
            answer = {"initial": case["linguistics"]["initial"], "clarified": from_ticks("pepperoni"), "difficulty": {"initial": "상", "clarified": "하"}}
            path.write_text(json.dumps({"format": "l-annotation-v2", "annotator": "alice",
                                        "answers": {case["id"]: answer}, "drafts": {}}, ensure_ascii=False), encoding="utf-8")
            report = Path(folder) / "report.md"
            output = subprocess.run([sys.executable, str(ROOT / "scripts/compare_linguistics.py"), str(path),
                                     "--output", str(report)], capture_output=True, text=True, check=True).stdout
            self.assertIn("draft vs alice: initial 1/1, clarified 0/1", output)
            text = report.read_text(encoding="utf-8")
            self.assertIn("pepperoni", text)
            self.assertIn("① 첫 말: 하 0개, 중 0개, 상 1개", text)
            self.assertIn("| 상 | 1 | 0 | 0 |", text)
            # Structure tier of case 1 against its first-utterance understanding label.
            self.assertIn(f"| {case['question']['difficulty']['ocs']} | 0 | 0 | 1 | 1 |", text)

    def test_labels_are_stored_in_the_data(self):
        import shutil
        case = json.loads((ROOT / "data/english100/benchmark_cases.jsonl").read_text(encoding="utf-8").splitlines()[0])
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "english100"
            shutil.copytree(ROOT / "data/english100", data)
            path = Path(folder) / "L_결과_bob.json"
            answer = {"initial": case["linguistics"]["initial"], "clarified": case["linguistics"]["clarified"],
                      "difficulty": {"initial": "중", "clarified": "하"}}
            path.write_text(json.dumps({"annotator": "bob", "answers": {case["id"]: answer}, "drafts": {}},
                                       ensure_ascii=False), encoding="utf-8")
            subprocess.run([sys.executable, str(ROOT / "scripts/compare_linguistics.py"), str(path), "--data",
                            str(data / "benchmark_cases.jsonl"), "--write-difficulty"], capture_output=True, check=True)
            stored = json.loads((data / "benchmark_cases.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(stored["question"]["difficulty"]["lcs"], {"initial": "중", "clarified": "하"})


if __name__ == "__main__":
    unittest.main()
