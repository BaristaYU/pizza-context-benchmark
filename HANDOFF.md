# Pizza Context Benchmark 작업 인수인계

다음 개발은 독립 NLU와 Planning 평가를 연결하는 작업이다. 팀원 L 검수는 사용자가 맡으며, 검수가 끝날 때까지는 Claude Code가 작성한 L 초안으로 개발한다.

## 현재 구현과 데이터

- GUI와 CLI는 같은 좌표 기반 주방 `mock-kitchen-4`를 사용한다. E2E 주문 처리와 참조 계획을 주는 독립 Tool Use는 실행할 수 있다. 모델 배치는 `scripts/run_benchmark.py`에서 시작한다.
- 독립 Reasoning은 `python scripts/run_benchmark.py --task reasoning`으로 실행한다. 재확인까지 반영한 참조 L과 공통 메뉴로 A를 생성한다. 문항별 응답과 형식 오류, 조건 차이는 문항 JSON에, 집계는 `summary.json`에 저장한다. [Reasoning 실행](docs/model_runs.md#독립-reasoning-평가)
- [영어 100문항](data/english100/benchmark_cases.jsonl)은 위키 주문에서 뽑았다. 각 문항에 주문 Q, 초기 주방 상태 S, 주문서 L, 제작 요구조건 A, 참조 계획 T, 실행 기록 E가 있다. 메뉴는 [data/menu.json](data/menu.json)에 있다.
- S는 공통 초기 상태다. T와 E는 A에 맞춰 생성하고 주방에서 재생해 검증한다. 공식 평가 전에는 L을 팀원 결과와 대조해 확정하고, A는 주문과 재확인 문장, 위키 레시피를 대조해 확인한다.
- 현재 작업 트리에는 README와 관련 문서 수정이 남아 있다. 작업을 시작할 때 `git status --short`로 현재 변경을 확인한다.

## 남은 개발

1. **NLU와 Planning을 연결한다.** NLU의 최초 주문과 재확인 주문은 각각 참조 L과 비교한다. `linguistics_form.validate`와 `linguistics_form.compare`를 사용한다. Planning은 참조 A, 초기 S와 도구 명세를 주고, 모델의 T를 같은 주방에서 재생해 실행 가능 여부와 A 충족, 제출 여부를 검사한다.
2. **실패 분석 보고서를 만든다.** 독립 평가와 기존 Tool Use, E2E 결과를 문항 ID로 연결한다. 형식 오류, 요구조건 오류, 계획 실행 실패와 도구 호출 오류를 기록하고, 문항별 통과 여부와 근거를 보여 준다. 기존 실행기는 `ai_runner.py`와 `batch_engine.py`, 진단과 보고서는 `diagnostics.py`와 `batch_report.py`에 있다.
3. **Computer Use를 연결한다.** Tk 주방 화면을 관찰하고 클릭, 드래그로 제작할 수 있게 한다. 모델이 보는 화면에는 주문과 조작에 필요한 주방만 포함한다. 정답과 참조 실행이 표시되는 SLATE 비교 패널은 평가자가 사용한다.

단계별 입력과 채점은 [평가 규칙](docs/benchmark_rules.md)과 [실행 채점](docs/execution_scoring.md)을 참고한다. 현재 E2E의 기본 모델 입력은 주문, 상태, 메뉴와 도구 명세다.

## L 검수 도구 배포

배포 파일은 `dist/L_annotator.zip`에 있다. 이 경로는 Git에서 제외된다. 새로 클론했거나 문항이 바뀌었으면 저장소 루트에서 아래 명령으로 다시 만든다.

```powershell
python scripts/build_l_annotator.py --output dist/L_annotator
```

두 팀원에게 1~50번, 51~100번을 맡긴다. 작성자는 압축을 풀고 `실행하기.bat`을 열어 최초 주문과 재확인 주문의 L, 이해 난이도를 기록한다. 결과인 `L_결과_<이름>.json`을 받으면 `scripts/compare_linguistics.py`로 초안과 대조한다. `--write-difficulty`는 이해 난이도를 저장하는 옵션이다. 최종 L은 차이를 검토해 확정한다. [작성과 검수 절차](docs/linguistics_form.md#초안과-ground-truth)

## 확인 명령

Python 3.10 이상을 사용한다. GUI와 L 작성 도구에는 Tkinter가 필요하다. 아래 명령은 저장소 루트에서 실행한다.

```powershell
python -m pizzabench.game_cli --list-cases
python -m pizzabench.game --headless --case practice_olive --plan examples/mock_game_olive.json
python -m unittest discover -s tests
```

API 키는 Git에서 제외되는 `configs/api_keys.local.json`에서 읽는다. 실제 모델 실행 전에는 비용을 추정한다. [모델 실행과 결과 위치](docs/model_runs.md)
