# CLI로 피자 제작 도구 사용하기

`python -m pizzabench.game_cli`는 프로세스를 유지하며 표준 입력으로 JSON 한 줄을 받아 도구를 실행하고, 표준 출력으로 JSON 한 줄을 반환합니다. 화면 없이 동작하며 Tkinter를 설치하지 않은 환경에서도 사용할 수 있습니다. GUI와 같은 `Kitchen` 제작 로직·State·최종 주문 채점을 사용합니다.

같은 세션을 Gemini·OpenAI·Anthropic 등의 모델 API가 조작하게 하려면 `--ai-provider`를 사용합니다. 사용법·비용 추정·배치 실행은 [모델 API 실행 안내](model_runs.md)에 있습니다.

## 시작

저장소 폴더에서 실행합니다.

```powershell
python -m pizzabench.game_cli
```

처음에는 `event: ready` 한 줄을 출력합니다. 이 메시지에는 최초 주문, 초기 State, 환경 버전, 도구 이름·설명·인수의 JSON Schema가 있습니다. 참조 정답과 재확인 문장은 포함하지 않습니다.

그다음 다음과 같이 요청을 입력합니다. `id`는 응답을 연결하는 선택 항목입니다.

```json
{"id":1,"tool":"create","args":{"dough":"regular"}}
{"id":2,"tool":"spread","args":{"pizza":1}}
{"id":3,"tool":"place_toppings","args":{"pizza":1,"kind":"olive","points":[[-0.4,0.2],[0.4,0.2]]}}
{"id":4,"tool":"observe","args":{}}
```

각 요청에 대해 `ok`, `tool`, `result`, `done`을 반환합니다. 제작 도구의 `result`는 바뀐 피자의 상태이며 토핑 좌표는 빠져 있습니다. 토핑 좌표를 포함한 전체 S는 `observe`로 받습니다. 실패한 요청에는 `error_type`과 `error`가 있으며 환경은 유지됩니다. 오류 응답을 읽은 뒤 수정한 호출을 계속 보낼 수 있습니다.

```json
{"id":5,"tool":"cut","args":{"pizza":1,"angle":0}}
```

굽기 전에 자르면 실패합니다. 이후 재료 적용, `bake`, `cut`, `serve`를 이어갈 수 있습니다. `bake`는 기다림 없이 바로 끝나고 피자를 커팅대로 옮깁니다. `clarify`는 주문의 “네?” 문장을 한 번 공개합니다.

모든 피자를 포장한 뒤 다음 요청으로 주문을 전달하고 채점합니다.

```json
{"tool":"finish","args":{}}
```

`finish`가 정상 실행되면 최종 평가와 `done: true`를 반환하고 프로세스가 종료됩니다. 아직 포장하지 못해 `finish`가 실패했다면 계속 제작할 수 있습니다. 종료 코드 0은 평가 성공, 1은 평가 실패 또는 `finish` 전 입력 종료, 2는 설정·파일 오류입니다.

## 독립 Tool Use 평가

참조 계획 T와 S₀를 주고 실행 능력을 평가하려면 `--reference-plan`을 사용합니다.

```powershell
python -m pizzabench.game_cli --reference-plan examples/mock_game_olive.json --output tool_run.json
```

서버는 별도 환경에서 참조 계획이 실행 가능하며 주문을 만족하는지 먼저 검증합니다. `ready`의 Task는 `tool_use`이고, 초기 State와 참조 계획을 제공합니다. 주문 해석을 다시 요구하지 않도록 주문 문장과 재확인 도구는 이 모드의 입력에서 제외합니다.

평가 결과는 다음 항목을 구분합니다.

| 항목 | 의미 |
| --- | --- |
| outcome | 최종 피자가 Answer를 만족하고 모든 피자가 포장·제출됐는가 |
| plan | 성공한 제작 호출의 대상·인수·순서가 제공된 구체적인 참조 계획과 일치하는가 |
| metrics | 도구 호출·실패·재확인 횟수와 시뮬레이션 시간 |

`evaluation.passed`는 outcome과 plan이 모두 통과해야 true입니다. 참조 계획을 제공하지 않은 `order_execution` 모드에서는 outcome으로 판정합니다.

현재 plan 검사는 구체적인 도구 호출 계획을 비교합니다. 도구 이름과 인수·대상·순서를 검사하며 숫자 인수에는 절대 오차 `1e-6`을 허용합니다. `observe`는 횟수가 달라도 됩니다. 실패한 호출은 별도 진단값으로 기록하고, 성공한 재시도가 계획을 충족하면 복구를 허용합니다. 참조에 없는 성공한 제작 행동은 추가 행동으로 기록합니다. 같은 최종 피자를 만드는 다른 유효한 계획을 인정하는 Planning 평가는 outcome을 사용합니다.

## 예시 계획을 파이프로 실행

[예시 JSONL 요청](../examples/mock_game_olive.jsonl)은 제작 호출과 마지막 `finish`를 포함합니다.

```powershell
Get-Content examples/mock_game_olive.jsonl | python -m pizzabench.game_cli --reference-plan examples/mock_game_olive.json --output tool_run.json
```

PowerShell과 Linux/macOS의 셸 모두 프로세스의 stdin/stdout에 연결할 수 있습니다. 통신 인코딩은 UTF-8입니다. 모델 실행기는 `ready`를 읽고, 도구 호출을 한 줄 보내고, 응답 한 줄을 읽는 과정을 반복합니다. 평가 모델의 파일 접근 범위에는 참조 정답과 서버 내부 데이터가 포함되지 않도록 구성합니다.

## 도구와 문항 확인

```powershell
python -m pizzabench.game_cli --list-tools
python -m pizzabench.game_cli --list-cases
python -m pizzabench.game_cli --case practice_well_done
```

도구별 조작 단위·좌표·재고·오븐 규칙은 [모의 게임 안내](mock_game.md)를 따릅니다. 도구 정의에는 `create`, `spread`, `paint`, `fill`, `place_toppings`, `bake`, `cut`, `serve`, `undo`, `discard`, `observe`와 세션용 `clarify`, `finish`가 있습니다. `fill`은 화면의 넓게 바르기와 같은 행동입니다.

## 실행 기록

`--output`으로 초기 State, 실제 도구 호출·응답·오류, 최종 State, 평가 결과, CLI 요청·응답을 저장합니다. 기존 파일을 덮어쓰지 않으므로 실행마다 새 경로를 지정합니다.

`score`는 기존 게임과 호환되는 최종 주문 판정입니다. `evaluation`에는 outcome, plan, metrics와 종합 통과 여부가 있습니다. `request_errors`는 모든 실패 요청 수, `protocol_errors`는 잘못된 JSON·요청 형식의 수입니다. `metrics.failed_calls`는 제작 환경의 trace에 기록된 실패 호출 수입니다.

`finish` 없이 stdin이 닫히면 상태는 `INCOMPLETE`이고 `score`와 `evaluation`은 null입니다. 최종 채점은 주문을 전달할 때 한 번 공개합니다.

채점 규칙과 현재 구현 범위는 [실행 채점](execution_scoring.md)에 정리합니다.
