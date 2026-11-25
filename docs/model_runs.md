# 모델 API로 주방 실행하기

`pizzabench.game_cli`가 표준 입력으로 받던 도구 호출을 모델 API가 보내도록 연결한 기능이다. 모델은 CLI 세션과 같은 `ToolEnvironment`에서 주문을 읽고, 좌표 기반 `Kitchen`(`mock-kitchen-4`)을 조작한 뒤 `finish`를 호출한다. 채점은 사람이 GUI에서 만들 때와 같은 코드로 한다. 화면(`game.py`)과 JSONL 프로토콜은 바뀌지 않았다.

배치 실행, 이어 실행, 시도 이력, 결과 보고서와 실행 비교는 main의 기능을 옮겨 왔다. 같은 기능을 게임 화면에서도 실행할 수 있다.

## 게임 화면에서 실행하기

```powershell
cd pizza_context_benchmark
py -m pizzabench.game
```

`game.py`는 패키지 안의 모듈을 불러오므로 파일 경로로 직접 실행하지 않고 `-m`으로 실행한다. 화면은 기본으로 영어 100문항(`data/english100/benchmark_cases.jsonl`)과 연습 주문 4개를 불러온다. 다른 문항 파일은 `--data`로 지정한다.

상단 AI 막대에서 서비스(`gemini`, `openai`, `anthropic`, `vllm`)와 모델, 사고 수준을 고르고, 현재 문항과 전체 문항 중 실행 범위를 정한 뒤 `AI 실행`을 누른다. 현재 문항은 모델이 화면의 주방을 직접 조작하므로 진행 과정이 그대로 보인다. 전체 문항은 배치 엔진으로 실행하며, 시작 전에 예상 비용을 보여 주고 확인을 받는다. `중지`는 진행 중인 요청이 끝난 뒤 멈춘다. 모델이 실행하는 동안에는 손으로 주방을 조작할 수 없다.

`SLATE 데이터`는 위에서부터 현재 문항, Q, 모델 출력, SLATE 비교를 보여 준다. 모델 출력의 진행 과정 탭은 요청마다 사고와 글, 도구 호출과 결과를 쌓고, 원본 응답 전체 탭은 서비스가 돌려준 응답을 그대로 보여 준다(서명과 암호화된 값만 길이로 줄인다). 실행 중에도 실시간으로 갱신된다. SLATE 비교는 S, L, A, T, E마다 정답과 모델 출력을 나란히 보여 준다. 현재 실행 방식은 모델이 L과 A를 따로 쓰지 않으므로 그 두 탭의 모델 쪽은 비어 있다. 정답이 들어 있으므로 Computer Use 평가의 관측 화면으로 쓰지 않는다. `채점 결과`는 이번에 사람과 모델이 완료한 문항의 주문 조건 충족, 요청 수, 추정 비용을 보여 주고, 전체 문항 실행의 HTML 보고서를 연다. 현재 문항 실행 기록은 `results/gui/`, 전체 문항 실행은 `results/run_*/`에 저장된다.

화면은 CLI와 같은 환경을 제공하도록 맞췄다. 버튼이나 조작 하나가 CLI 도구 호출 하나에 대응한다(`오븐에 굽기`는 `bake`, 토핑 클릭이나 드래그는 `place_toppings`, `커터 선택` 후 드래그는 `cut`). 다시 만들기, 다음 주문, 기록 저장은 CLI에 없는 기능이라 없앴고, 문항 선택은 상단 막대로 옮겼다. 모든 버튼은 항상 누를 수 있고, 할 수 없는 동작이면 CLI와 같은 오류를 하단 줄에 표시한다. 재확인 문장이 있는지도 CLI처럼 `네?`를 눌러야 알 수 있다. 다음 행동 안내 문구, 만들기 버튼의 순서 번호, 배치 가이드 점은 CLI에 없는 힌트라서 뺐다.

## 키 설정

`configs/api_keys.local.json`에 키를 넣는다. 이 파일은 Git에서 제외된다. 서비스 이름(`gemini`, `openai`, `anthropic`), 모델 계열 이름(`gpt`, `claude`), 환경변수 이름(`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) 중 어느 것으로 적어도 읽는다. 같은 이름의 환경변수가 있으면 파일보다 우선한다. 다른 위치의 파일은 `--api-keys`로 지정한다.

```json
{"gemini": "...", "gpt": "...", "claude": "..."}
```

키는 요청 헤더에만 들어간다. 결과 파일·오류 메시지·보고서에는 기록하지 않으며, 배치 결과는 저장 전에 키 문자열을 `[REDACTED]`로 바꾼다.

## 지원 서비스

| 서비스 | API | 기본 모델 |
| --- | --- | --- |
| `gemini` | `generateContent` | `gemini-3.1-flash-lite` |
| `openai` | Responses | `gpt-5.4-nano` |
| `anthropic` | Messages | `claude-haiku-5-5` |
| `vllm` | vLLM의 OpenAI 호환 Chat Completions | `configs/agent_models.json`의 로컬 모델 |
| `mistral` | OpenAI 호환 Chat Completions (main에서 이식) | 없음, `--ai-model` 필수 |

모든 어댑터는 Python 표준 라이브러리로 HTTP를 호출하며 새 의존성을 추가하지 않았다. 기본 모델은 가장 저렴한 연결 확인용이다. 비교 실험에 쓸 모델은 `--ai-model`로 정확한 ID를 지정한다. 계정에서 쓸 수 있는 모델은 `--list-models`로 확인하며, 이 조회는 토큰을 쓰지 않는다. 2026-11-24에 `gemini`, `openai`, `anthropic`은 실제 API로 확인했고 `mistral`은 키가 없어 모의 응답으로만 검증했다.

main에 있던 Groq와 OpenRouter는 모델 실행기에서 지웠다. 두 서비스의 무료 한도(하루 요청 수와 토큰 수)로는 벤치마크 한 번을 끝낼 수 없기 때문이다. Mistral의 무료 플랜은 초당 1요청과 월 토큰 한도 안에서 실행할 수 있어 남겼다. 영어 25문항 파일럿의 서비스 설정(`configs/english_models.json`)은 별도 기능이라 그대로 두었다.

모든 서비스에서 한 응답에 여러 도구를 호출하는 병렬 호출을 허용한다. Gemini는 병렬 호출을 끌 수 없으므로, OpenAI와 vLLM에도 `parallel_tool_calls=true`를 보내 조건을 맞췄다.

### 사고 내용의 보존과 표시

세 서비스 모두 서버에 대화를 저장하지 않으므로, 실행기가 매 요청마다 대화 전체를 다시 보낸다. 사고 내용은 서비스가 돌려준 형태 그대로 다음 요청에 다시 넣어야 이어진다. Claude는 thinking 블록, Gemini는 thought signature, OpenAI는 Responses API의 암호화된 reasoning 항목(`store: false`, `include: reasoning.encrypted_content`), vLLM은 `reasoning_content`를 다시 보낸다.

모니터링을 위해 사고 요약도 받는다. Claude는 `thinking.display: summarized`, Gemini는 `includeThoughts`, OpenAI는 `reasoning.summary: auto`를 쓴다. 표시 방식만 바뀌며 사고 자체와 과금은 같다.

사고 수준은 `--reasoning-effort low|medium|high`(화면의 사고 수준)로 세 서비스에 같은 값을 보낸다. Gemini의 `thinkingLevel`, OpenAI의 `reasoning.effort`, Claude의 `output_config.effort`로 바뀐다. 기본값은 medium이다. `default`를 고르면 각 모델의 기본값을 쓰는데, 기본값에서는 사고 여부가 서비스마다 다르다. 2026-11-25 실측에서 Claude Haiku 5.5는 기본값으로 사고했고, GPT-5.4 nano와 Gemini 3.1 Flash-Lite는 사고 토큰이 0이었다.

## 로컬 모델 (vLLM)

48GB GPU 1장에서 Qwen3.8-27B와 Gemma 4 31B를 비교하는 것을 기준으로 설정했다. Computer Use 평가 후보는 `computer_use_models`에 따로 적었다(실행기는 아직 없다). Qwen3.8의 샘플링과 도구 호출 파서는 모델 카드에서 확인하지 못해 Qwen3.6 값을 임시로 쓴다. 두 모델 모두 FP8로 서빙해 정밀도를 맞추고, 샘플링은 각 모델 카드의 권장값을, 사고 모드는 프런티어 모델과 같이 켠 상태를 쓴다. 서빙 명령과 설정값은 `configs/agent_models.json`의 `local_models`에 있다. Gemma 4의 vLLM 도구 호출 파서 이름은 모델 카드에 없어서, 서빙 전에 vLLM 문서에서 확인해야 한다.

```powershell
python -m pizzabench.game_cli --case en100_000007 --ai-provider vllm --ai-model Qwen/Qwen3.8-27B --base-url http://GPU서버:8000/v1
```

vLLM이 돌려주는 사고 내용(`reasoning_content`)은 다음 요청의 대화에 그대로 남긴다. 로컬 모델에는 토큰 단가가 없으므로 비용 한도 대신 요청 수와 도구 호출 수로 예산을 맞춘다. 실행 시간은 GPU 성능에 따라 달라지므로 통과 조건으로 쓰지 않고 따로 기록한다. 아직 실제 vLLM 서버로는 검증하지 않았다.

## 한 문항 실행

```powershell
python -m pizzabench.game_cli --case en100_000007 --ai-provider anthropic --estimate-cost
python -m pizzabench.game_cli --case en100_000007 --ai-provider anthropic --max-cost 0.10 --output run.json
```

`--estimate-cost`는 생성 요청 없이 낙관·보수 비용을 계산한다. 낙관 추정은 모델이 참조 계획과 같은 호출을 한 턴에 하나씩 한다고 가정하고, 보수 추정은 `--max-requests`까지 모두 쓰며 턴마다 가장 큰 응답과 추론 400토큰이 붙는다고 가정한다. 참조 계획은 `english100.plan_from_answer`로 만들어 오프라인으로 실행해 보고, 그 대화의 크기를 잰다. Gemini와 Anthropic은 무료 토큰 계산 엔드포인트로 실측하고, 계산 엔드포인트가 없는 OpenAI는 Gemini 실측값보다 높은 고정 비율을 쓴다.

실행 결과는 요약을 출력하고, `--output`에는 전체 기록을 남긴다. 기록에는 실제 호출과 응답, 최종 상태, 주문 채점, 종료 이유, 요청 수, 토큰 사용량과 추정 비용이 들어간다.

| 옵션 | 기본값 | 뜻 |
| --- | --- | --- |
| `--max-requests` | 60 | 모델 요청 상한 |
| `--max-tools` | 150 | 도구 호출 상한 |
| `--max-seconds` | 900 | 실행 시간 상한 |
| `--max-cost` | 없음 | 누적 추정 비용이 이 금액에 이르면 다음 요청을 보내지 않는다 |
| `--request-interval` | 3 | 요청 시작 사이 간격(초) |
| `--rules` | 사용 안 함 | `docs/pizza_domain_rules.md`를 `ready` 이벤트 앞에 넣는 별도 실험 조건 |
| `--reasoning-effort` | medium | 세 유료 서비스에 같은 사고 수준(low, medium, high)을 지정. `default`는 각 모델의 기본값 |
| `--max-output-tokens` | 8192 | Anthropic의 `max_tokens`. OpenAI는 다른 값을 줄 때만 보낸다 |

비용 한도는 요청을 보내기 전에 확인한다. 따라서 한도를 넘기는 마지막 요청 하나만큼 초과할 수 있다. 단가는 `configs/agent_models.json`의 공개 가격이며 실제 청구서와 다를 수 있다. 단가가 없는 모델에는 비용 한도를 걸 수 없다.

## 모델에게 보이는 것

모델에게 보내는 첫 메시지는 CLI가 시작할 때 출력하는 `ready` 이벤트에서 도구 목록만 뺀 JSON이다. 여기에는 공개된 주문 문장, 관측 가능한 주방 상태, 메뉴(`data/menu.json`)가 들어 있다. 메뉴는 이름 붙은 피자의 구성과 토핑 범주를 알려 주는 환경 정보이며, 사람도 GUI의 메뉴판으로 같은 내용을 본다. 도구 목록과 각 도구의 설명은 API의 도구 정의로 전달한다. 작업 지시문이나 시스템 프롬프트는 넣지 않으므로, 모델은 게임 환경만 보고 무엇을 할지 스스로 정한다.

모델이 도구를 호출하지 않고 글로만 답하면, 지시 문장 대신 `observe`와 같은 현재 관측을 돌려준다. 정답 A와 참조 계획, 참조 실행은 채점 쪽에만 있다. 재확인 문장은 모델이 `clarify`를 호출할 때만 공개한다.

### S의 표현

CLI 프로토콜 4(`pizza-tools-jsonl-4`)는 주방 버전 4(`mock-kitchen-4`)를 따르고, 주문 실행 모드의 `ready`에 메뉴를 넣는다. 토핑은 좌표 목록을 받는 `place_toppings` 한 번으로 여러 개를 놓고, `bake`는 기다림 없이 바로 끝나 커팅대로 옮겨지므로 `wait`와 `take_out`은 없다. 제작 도구의 응답은 바뀐 피자의 상태만 담고 토핑 좌표는 빼며, 토핑 좌표를 포함한 전체 S는 `observe`로 받는다. 이 변경으로 영어 100문항의 참조 호출은 12,271회에서 1,885회로 줄었고, 100문항 전체 실행의 추정 입력은 약 25억 토큰에서 약 1,270만 토큰으로 줄었다.

도구 응답과 관측은 공개용 S를 돌려준다. 주방은 복원과 되돌리기를 위해 칠한 격자 칸(`coatings`)과 되돌리기 기록(`history`)을 내부에 보관한다. 공개용 S에서는 격자 칸 대신 재료별 영역 도포 비율(`coverage`, whole, left, right 각각 0부터 1)을 주고, 행동 기록인 되돌리기 기록은 뺀다. 토핑 좌표(`pieces`)는 실제 상태이므로 그대로 둔다.

이전에는 응답 하나가 약 1만 5천 자여서 한 문항의 마지막 요청이 13만 토큰을 넘었다. 지금은 응답이 약 500자에서 2,600자이고 마지막 요청도 약 2만 7천 토큰 이하다. 사람이 CLI로 받는 S와 모델이 받는 S는 같다. 채점과 저장되는 실행 기록(E)은 내부 상태를 사용한다.

## 배치 실행과 이어 실행

```powershell
python scripts/run_benchmark.py --provider anthropic --estimate-cost
python scripts/run_benchmark.py --provider anthropic --max-cost 0.30 --max-total-cost 2.00
python scripts/run_benchmark.py --provider anthropic --resume results/run_20261124_...
```

기본 대상은 영어 100문항이다. `--cases`로 문항을 고르고, `--include-practice`로 한국어 연습 주문 4개를 포함할 수 있다. 다른 Q-SLATE 파일은 `--data`로 지정한다. 모든 문항이 주방에서 열리는지 먼저 확인하며, 하나라도 열리지 않으면 요청을 보내기 전에 중단한다.

결과는 `results/` 아래에 문항별 JSON, `history/`의 시도 이력, `summary.json`, `report.html`로 저장된다. 이어 실행은 main과 같다. 완료 선언한 문항은 조건 미충족이어도 다시 호출하지 않고, API 오류·중단·요청 한도·비용 한도·미실행 문항만 초기 상태에서 다시 시작한다. 이전 시도는 지우지 않는다. HTTP 429를 받으면 배치를 멈추고 남은 문항은 미실행으로 남긴다. `--max-total-cost`는 이번 실행에서 쓴 추정 비용의 합이 한도에 이르면 다음 문항을 시작하지 않는다.

## 통제 지문과 실행 비교

배치마다 두 지문을 기록한다.

| 지문 | 포함하는 것 | 쓰임 |
| --- | --- | --- |
| `control_fingerprint` | 프롬프트 형식, CLI 프로토콜 버전, 규칙 문서 사용 여부, 도구 정의, 주방과 채점, 메뉴, 실행기 소스, 데이터, 요청과 도구와 시간과 비용 한도 | 비교할 실행끼리 같아야 하는 실험 조건 |
| `service_fingerprint` | 서비스, API 종류, 어댑터 소스, 출력 한도·effort 같은 생성 설정, 요청 간격·제한 시간 | 같은 실행을 이어 갈 때 같아야 하는 서비스 설정 |

이어 실행은 두 지문이 모두 같아야 한다. 실행 비교는 `control_fingerprint`가 같으면 공통 완료 성공률을 산출하고, 서비스 설정이 서로 다르면 그 사실을 경고로 표시한다. main은 서비스의 API 종류까지 하나의 지문에 넣어 서로 다른 서비스의 실행을 비교할 수 없었다. 서비스 설정을 실험 조건과 분리하되 숨기지 않는 쪽으로 정리한 것이다.

소스 해시는 BOM을 빼고 줄바꿈을 LF로 맞춘 내용으로 계산한다. 체크아웃 방식에 따라 CRLF가 되거나 BOM이 붙어도 같은 코드면 지문이 같다.

```powershell
python scripts/compare_runs.py results/run_a results/run_b --output-dir results/comparison
```

비교는 저장된 결과만 읽고 API를 호출하지 않는다. 비교 보고서에는 실행별 누적 추정 비용도 표시한다.

## 검증

```powershell
python -m unittest discover -s tests
```

`tests/test_ai_runner.py`와 `tests/test_batch_engine.py`는 네트워크 없이 서비스별 요청 형식, 사고 내용의 재전송과 요약 추출, 응답 해석, 키 비노출, 비용 한도, 공개용 S, 이어 실행, 통제 지문과 비교를 검사한다. `tests/test_game_panels.py`는 화면의 모델 실행, 전체 문항 실행, SLATE 데이터 창, 채점 결과 창을 검사한다. 모의 응답은 실행기 검증용이며 모델 성능이 아니다.
