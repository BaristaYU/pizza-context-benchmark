"""Build the stand-alone L annotation tool for non-developer annotators.

    python scripts/build_l_annotator.py --output ../L_annotator

Writes one .pyw file with the order form and the 100 orders inside, a .bat launcher and
a short guide, then zips the folder. Annotators need only Python (tkinter is part of the
python.org installer). Questions follow the case numbers, which alternate the structure
difficulty tiers, so questions 1-50 and 51-100 can be split between two annotators. No
difficulty is shown in the tool.
"""

import argparse
import json
from pathlib import Path
import sys
import zipfile

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from pizzabench import linguistics_form as form  # noqa: E402

APP = REPO / "tools" / "l_annotator_app.py"
DATA = REPO / "data" / "english100" / "benchmark_cases.jsonl"

LAUNCHER = "\r\n".join([
    "@echo off", 'cd /d "%~dp0"',
    'where pyw >nul 2>nul && (start "" pyw -3 L_annotator.pyw & exit /b)',
    'where pythonw >nul 2>nul && (start "" pythonw L_annotator.pyw & exit /b)',
    "echo Python is not installed. Install it from https://www.python.org and run this again.",
    "pause", ""])
README = """피자 주문서 작성 도구

1. Python이 설치되어 있어야 합니다. 없다면 python.org에서 설치하고, 설치 화면의 'Add python.exe to PATH'를 체크합니다.
2. 이 폴더의 '실행하기.bat'(또는 L_annotator.pyw)을 더블클릭합니다.
3. 작성자 이름을 적고 '시작'을 누릅니다. 맡은 문항 번호를 위의 드롭다운에서 고릅니다.
4. 문항마다 ① 첫 주문서를 작성하고, '네?'를 눌러 다시 들은 뒤 ② 주문서를 작성합니다. 아래에서 ①과 ②의 이해 난이도를 각각 고르고 '저장하고 다음'을 누릅니다.
5. 결과는 이 폴더의 'L_결과_<이름>.json'에 저장됩니다. 다 끝나면 이 파일을 보내 주세요.

중간에 닫아도 같은 이름으로 다시 시작하면 이어서 할 수 있습니다. 작성 중이던 문항도 저장되어 있으며, 드롭다운에 '작성 중'으로 표시됩니다. 작성 규칙은 프로그램의 '작성 안내' 버튼에 있습니다.
"""


def ordered(cases):
    return sorted(cases, key=lambda case: case["id"])


def payload(data_path=DATA):
    cases = [json.loads(line) for line in Path(data_path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    questions = [{"number": number, "id": case["id"], "order_text": case["question"]["order_text"],
                  "clarification_text": case["question"].get("clarification_text")}
                 for number, case in enumerate(ordered(cases), 1)]
    return {"form_version": form.FORM_VERSION, "pizza_keys": list(form.PIZZA_KEYS), "side_keys": list(form.SIDE_KEYS),
            "pizza_options": [(key, label) for key, (label, _) in form.PIZZA_OPTIONS.items()],
            "side_groups": [(title, list(group.items())) for title, group in form.SIDE_GROUPS],
            "single_choices": [dict(choice, keys=list(choice["keys"])) for choice in form.SINGLE_CHOICES],
            "guide": form.GUIDE_KO, "questions": questions}


def build(output, data_path=DATA):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    source = APP.read_text(encoding="utf-8")
    marker = "EMBEDDED = None  # 배포 파일을 만들 때 문항지와 문항으로 채워진다."
    if source.count(marker) != 1:
        raise ValueError("EMBEDDED marker not found in the app source")
    embedded = "EMBEDDED = json.loads(%r)" % json.dumps(payload(data_path), ensure_ascii=False)
    (output / "L_annotator.pyw").write_text(source.replace(marker, embedded), encoding="utf-8")
    (output / "실행하기.bat").write_bytes(LAUNCHER.encode("ascii"))
    (output / "사용법.txt").write_text(README, encoding="utf-8-sig")
    archive = output.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name in ("L_annotator.pyw", "실행하기.bat", "사용법.txt"):
            zipped.write(output / name, f"{output.name}/{name}")
    return output, archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=REPO.parent / "L_annotator")
    parser.add_argument("--data", type=Path, default=DATA)
    options = parser.parse_args(argv)
    folder, archive = build(options.output, options.data)
    print(f"tool folder: {folder}\nzip to send: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
