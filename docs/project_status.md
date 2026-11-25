# Data, Tech 인수인계

이 프로젝트는 고객의 피자 주문을 읽고, 제작 조건을 정하고, 계획을 세워 실제로 만드는 과정에서 LLM의 능력을 평가한다. Data 파트는 어떤 주문에 무엇을 정답으로 인정할지 정한다. Tech 파트는 그 주문을 모델에게 주고 결과를 채점하는 프로그램을 만든다. 아래 내용은 2026-11-25 기준이다.

## Data 파트

### 영어 100문항

평가 표본은 [영어 100문항](../data/english100/benchmark_cases.jsonl)이다. [위키 자료](../data/wiki/README.md)의 일반 주문(고정, 이름 붙은, 범주 레시피) 가운데 이 주방에서 만들 수 있는 주문을 구조 난이도 하 33, 중 33, 상 34로 뽑았다. 위키 레시피 하나에서 주문 하나만 뽑았고, 문항 번호는 구조 난이도를 번갈아 붙였다. 문항마다 다음 내용이 같은 ID로 연결돼 있다.

- Q: 위키에 있는 최초 주문과 "네?"를 눌렀을 때 나오는 재확인 문장
- S: 모든 문항에 같은 초기 주방 상태(일반, 밀 도우, 토마토, 페스토 소스, 치즈, 토핑 28종, 각 100개)
- L: 최초 주문만 읽은 주문서와 재확인까지 읽은 주문서
- A: 최종 제작 요구조건
- T, E: A를 만족하는 참조 계획과 그 계획을 실제로 실행한 기록

A는 주문의 위키 레시피에 주문이 요구한 커팅과 두 번 굽기를 더한 것이며, 문항의 `source`에 위키 위치와 레시피 표기를 남겼다. 위키 레시피가 메뉴나 주문 내용과 어긋나는 주문 9개는 뽑지 않았고, 이유는 `selection.json`에 있다. 위키의 현재 주문 목록에 없는 이벤트 토핑(삼겹살, 감자, 장미 꽃잎, 두부)은 쓰지 않는다. 문항을 다시 뽑으려면 `scripts/select_english100.py`를, A나 검수 기록을 고친 뒤에는 `python -m pizzabench.english100`을 실행한다.

문항의 `question.difficulty`에는 A에서 계산한 구조 난이도와 팀원이 고를 이해 난이도(첫 말, 다시 들은 뒤)가 함께 저장된다. 이해 난이도 비율이 크게 치우치면 같은 구조 난이도의 예비 주문으로 문항을 바꿔 조정하며, 방법은 [L 주문서 형식](linguistics_form.md)의 난이도 절에 있다.

### L 주문서와 Ground Truth

L은 모든 문항이 함께 쓰는 객관식 주문서다. 형식과 작성 규칙은 [L 주문서 형식](linguistics_form.md)에 있다. Claude Code가 작성한 L 초안은 `pizzabench/english100_linguistics.py`에 있다. 단계별 평가를 개발하고 검증할 때 이 데이터를 참조한다. 두 팀원이 작성 도구로 50문항씩 나누어 주문서를 작성하고, 초안과 비교해 Ground Truth를 정한다. 팀원은 각 문항에서 첫 말만 들었을 때와 다시 들은 뒤의 이해 난이도도 하, 중, 상으로 고른다.

### 메뉴

손님은 "Hawaiian"처럼 레시피 이름으로, 또는 "냄새가 강한 토핑 전부"처럼 범주로 주문한다. 이름 붙은 피자 20종의 구성과 토핑 범주 15종은 [메뉴](../data/menu.json)에 있다. 이름 붙은 피자는 위키의 [Recipe Book](https://good-pizza-great-pizza.fandom.com/wiki/Recipe_Book)을, 범주는 위키 주문 목록의 범주 주문(All Meats, Fruit Pizza, Smelly Toppings 등)을 따른다. 메뉴는 환경의 일부로 모든 모델과 사람에게 같은 내용으로 제공한다. CLI는 ready 이벤트에, Reasoning과 E2E의 Task 입력에는 `menu` 필드로, GUI는 메뉴판 창으로 보여 준다.

## Tech 파트

### 제작 환경과 채점

GUI(`python -m pizzabench.game`)와 CLI(`python -m pizzabench.game_cli`)는 같은 `Kitchen`(`mock-kitchen-4`)을 사용한다. 소스와 치즈는 격자 칸으로, 토핑은 좌표로 기록하고, 모델과 사람에게는 영역별 도포율을 보여 준다. 사용법은 [모의 게임 안내](mock_game.md)와 [CLI 안내](tool_use_cli.md)에 있다.

채점은 문항별 통과와 실패다. 최종 피자가 A를 만족하는지 보고, 참조 계획을 준 Tool Use에서는 그 계획을 이행했는지도 본다. 점수형 보조 지표는 두지 않고, 실패한 문항은 오류 목록과 실행 진단으로 원인을 분석한다. 기준은 [실행 채점](execution_scoring.md)에 있다.

### 모델 실행

모델은 지시문 없이 CLI의 ready 이벤트(주문, 상태, 메뉴)와 도구 명세만 받고 스스로 주문을 처리한다. Gemini, OpenAI, Anthropic API와 Mistral, vLLM으로 띄운 로컬 모델을 지원한다. GUI의 AI 막대에서 한 문항 또는 100문항 전체를 실행하고, `scripts/run_benchmark.py`로 같은 일괄 실행을 명령행에서 할 수 있다. 실행 전에 비용을 추정하고, 실행마다 통제변수 지문을 저장해 같은 조건의 실행끼리만 비교한다. 자세한 내용은 [모델 실행](model_runs.md)에 있다.

### 다음 작업

1. 팀원의 L 작성 결과를 받아 `scripts/compare_linguistics.py`로 초안과 비교하고 Ground Truth를 확정한다. `--write-difficulty`로 이해 난이도를 데이터에 저장하고, 비율이 치우치면 예비 주문으로 문항을 바꾼다.
2. 단계별 평가를 연결한다. NLU는 Q에서 L을, Reasoning은 L과 메뉴에서 A를, Planning은 A와 S에서 T를 만들게 하고, E2E는 전체를 한 번에 수행하게 한다. 모델이 쓴 L은 `linguistics_form.compare`로, 모델이 쓴 A는 `l_to_a.same_answer`로 채점할 수 있다. 두 비교 함수는 있지만, 모델에게 단계 과제를 주고 답을 받아 채점, 기록하는 실행 경로는 아직 없다.
3. 실패한 문항을 단계별로 모아 보는 실패 분석 리포트를 만든다.
4. Computer Use 모드를 설계한다. 서비스별 화면 조작 도구와 화면 조작이 가능한 로컬 모델을 같은 Tk 창에 연결한다.

## 작업을 시작할 때

Python 3.10 이상과 Tkinter가 필요하다. 저장소 루트에서 다음 명령으로 테스트와 데이터를 확인한다.

```powershell
python -m unittest discover -s tests
python -m pizzabench.english100
python -m pizzabench.game_cli --list-cases
```

코드는 제작 상태를 관리하는 `pizzabench/kitchen.py`, 주문과 채점을 묶는 `game.py`, 도구 통신을 담당하는 `game_cli.py`부터 읽는다. 주문 충족은 `grading.py`, 계획 이행은 `execution_eval.py`, 모델 실행은 `ai_runner.py`와 `providers.py`에 있다. 기존 계획 재생기 `environment.py`는 `schemas/`와 `data/samples/`의 이전 형식(환경 버전 `0.2`)을 검사하는 데만 쓴다.

기능별 작업 브랜치에서 진행하고, 공유하는 필드나 채점 의미를 바꿀 때는 관련 문서와 테스트를 함께 갱신한다.
