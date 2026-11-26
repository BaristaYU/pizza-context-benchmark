# Q-SLATE 데이터 구조

영어 100문항의 L은 [L 주문서 형식](linguistics_form.md)을 따릅니다. 아래 L 예시는 이전 환경의 형식입니다. L과 A의 경계는 [L과 A 설계](linguistics_answer_design.md)에 정리합니다. Q·S·A·T·E의 현재 저장 형식은 아래 설명을 따릅니다.

## 영어 100문항의 현재 형식

`data/english100/benchmark_cases.jsonl`은 `mock-kitchen-4` 환경의 Q, S, L, A, T, E를 모두 담는다. Q는 `language`, `order_text`, `clarification_text`, 그리고 난이도 기록 `difficulty`다. `difficulty`는 A에서 계산한 구조 난이도(`ocs` 등)와 팀원이 고른 이해 난이도(`lcs.initial`, `lcs.clarified`)를 담는다. `source`는 위키 데이터 안의 위치(`wiki_key`), 판, 분류, 레시피 표기, 위키 설명, 주문이 요구한 커팅과 두 번 굽기다. 초기 S에는 복원 가능한 Kitchen 스냅샷을, T에는 실제 좌표와 각도를 사용하는 도구 호출을, E에는 실제 호출 기록과 최종 상태를 기록한다. `source`, `review`, `reference_evaluation`은 출처, 검수, 채점용 필드다. Task 입력에는 `build_task_input`이 선택한 정보만 전달한다.

파일별 역할과 생성 명령은 [데이터 안내](../data/README.md)에 있다. 아래 `schemas/`와 기존 10문항은 이전 환경 `0.2`의 데이터 예시다.

실제 데이터는 JSONL로 저장합니다. 한 줄에 한 건을 담으며 파일 전체를 배열로 감싸지 않습니다. `schemas/Q-SLATE/*.json`은 각 구성 요소의 데이터 예시이며, `schemas/benchmark_case_schema.json`은 한 평가 문항 전체의 예시입니다.

## 파일과 연결

| 파일 | 한 건의 구성 |
| --- | --- |
| [question_fixed_recipes.jsonl](../data/samples/question_fixed_recipes.jsonl) | 수집한 원문 Q: id, difficulty, language, order_text, clarification_text, recipe_text |
| [benchmark_cases_fixed_recipes.jsonl](../data/samples/benchmark_cases_fixed_recipes.jsonl) | 평가 문항: id, environment_version, question, state, linguistics, answer, tool_calling, execution |

각 평가 문항에 Q·S·L·A·T·E를 함께 저장합니다. `question`은 원문 Q, `state`는 초기 S이며, `linguistics`, `answer`, `tool_calling`은 정답 L·A·T입니다. `execution`에는 참조 T를 실행해 얻은 E를 저장합니다. 문항의 `id`와 원문의 `question.id`는 재정렬해도 유지합니다.

모델 실행 결과에는 문항을 연결하는 `case_id`, 환경 버전, 초기 S, 사용한 T, 관측한 E와 채점 결과 `score`를 기록합니다. 모델 실행 기록은 참조 데이터와 구분해 보관합니다.

## 모델에 제공하는 입력

평가 실행기는 통합 문항에서 Task에 필요한 필드만 선택합니다. `build_task_input`은 아래 입력 범위를 적용합니다.

| Task | 선택하는 입력 |
| --- | --- |
| NLU | question의 order_text |
| Reasoning | 참조 linguistics와 공통 menu. 독립 실행에서는 재확인까지 반영한 L |
| Planning | 정답 answer와 초기 state |
| Tool Use / Computer Use | 참조 tool_calling과 초기 state |
| E2E | 주문 텍스트와 초기 state |

NLU와 E2E에서 `clarified=True`는 재확인 문장을 공개합니다. Reasoning에서 같은 옵션은 L의 `clarified` 버전을 선택합니다. question의 recipe_text와 참조 execution은 채점·검수에 사용합니다. 공통 메뉴와 도구 명세는 Task의 입력 범위에 맞게 제공합니다.

```python
from pizzabench import build_task_input

model_input = build_task_input(case, "E2E")
```

평가용 도구와 파일 접근에도 같은 입력 범위를 적용해야 합니다. Computer Use 평가 화면을 구성할 때에는 검수용 정답 탭을 제외하고 관측 가능한 환경 상태를 표시합니다.

## Q: 원문

| 필드 | 내용 |
| --- | --- |
| id | 원문 데이터의 고유 ID |
| difficulty | 난이도. 미정이면 null |
| language | ko, en 등 언어 코드 |
| order_text | 고객의 주문 원문 |
| clarification_text | 재확인 주문 원문. 없으면 null |
| recipe_text | 레시피 정답 원문. 미수집이면 null |

Q는 이 여섯 필드로 유지하며 주문·재확인 주문·레시피의 표현을 보존합니다. 모델에는 `order_text`를 제공하고 “네?”를 선택했을 때 `clarification_text`를 공개합니다. `recipe_text`는 정답 작성과 검수에 사용합니다.

예시: [Q](../schemas/Q-SLATE/question_schema.json), [문항 전체](../schemas/benchmark_case_schema.json).

## S: 환경 상태

| 필드 | 내용 |
| --- | --- |
| inventory | 도우·소스·치즈·토핑의 남은 재고 |
| pizza_count | 환경에 생성된 피자 수. pizzas의 길이와 같음 |
| pizzas | 피자별 재료, 수량, 영역과 제작 단계 |
| submitted | 피자가 있고 모든 피자가 제출됐으면 true |

초기 상태 S₀는 Planning과 Execution의 입력입니다. 실행 중에도 같은 형식으로 현재 상태를 관측할 수 있습니다. 준비된 피자가 있으면 해당 피자와 제작 단계도 초기 S에 기록합니다.

도우·토핑 재고는 개수이며 소스·치즈는 피자 전체에 적용할 수 있는 분량입니다. 전체 적용은 1, 반쪽 적용은 0.5를 사용합니다. 샘플의 초기 재고는 재료별 100이고 준비된 피자는 없습니다. 도구 명세와 제작 규칙은 공통 환경 설정으로 제공합니다.

예시: [S](../schemas/Q-SLATE/state_schema.json).

## L: 문장 의미 분석

L은 문장에 표현된 레시피 이름, 재료, 수량, 제외 조건과 조건의 적용 대상을 기록합니다.

- `recipe`는 문장에서 부른 레시피 이름입니다. “하와이안”을 재료로 풀어내는 일은 A 단계에서 합니다.
- 재료·수량·영역 필드는 문장에 나타난 조건을 기록합니다. “녹색 소스”, “갈색 도우”는 L에서 `green`, `brown`으로 남기고 A에서 재료 규칙으로 해석합니다.
- 방향이 없는 두 반쪽은 `half_1`, `half_2`로 기록해 같은 쪽·다른 쪽의 관계를 보존합니다. 명시된 `left`, `right`는 그대로 기록합니다.
- `oven_passes`는 명시한 오븐 횟수이고 `cuts`는 조각 수입니다. 사람 수와 인당 조각 수로 피자 수를 계산하는 일은 A 단계에서 합니다.
- `initial`은 최초 주문의 분석입니다. `clarified`는 주문과 공개된 재확인 문장을 함께 읽은 분석이며, 재확인 문장이 없으면 생략합니다.

양파에 관한 이야기 후 재확인에서 주문을 밝히는 샘플은 다음처럼 기록합니다.

```json
{
  "initial": {"intent": "statement", "topic": "onion"},
  "clarified": {"pizza_count": 1, "pizzas": [{"recipe": "onion"}]}
}
```

NLU는 공개된 문장에 해당하는 분석을 평가합니다. 예시: [L](../schemas/Q-SLATE/linguistics_schema.json).

## A: 최종 제작 요구조건

A는 주문과 공개된 재확인 문장, 레시피·재료 규칙을 바탕으로 작성한 채점 조건입니다. 원문에 있는 판수·수량·굽기·조각 수 조건도 A에 반영합니다. 생략한 속성은 실행 가능한 값 중 자유롭게 선택할 수 있습니다.

`pizza_count`를 지정하면 판수를 비교합니다. 여러 피자는 `pizzas` 배열에 기록하고 순서 없이 일대일 대응시켜 비교합니다. 완성 주문의 정답이 여러 개면 `alternatives` 배열에 각 주문 전체를 보존합니다. 한 대안의 조건을 모두 만족해야 통과합니다.

예시: [A](../schemas/Q-SLATE/answer_schema.json).

### A와 환경 상태의 피자 필드

| 필드 | 기록 방법 |
| --- | --- |
| id | 환경 상태에서 T의 pizza 인자와 연결하는 피자 ID |
| stage | 환경 상태의 제작 단계: dough, preparation, baked, cut, submitted |
| dough | regular, wheat 등 도우 종류 |
| sauce | 소스 종류 목록. A의 ["any"]는 종류 자유·소스 있음, []는 없음 |
| sauce_placement | 소스별 영역. {"tomato":"left","pesto":"right"} |
| cheese | 있음 true, 없음 false |
| cheese_placement | whole, left, right |
| toppings | 순서 없는 토핑 종류 목록. 없음은 [] |
| topping_counts | 종류별 수량. {"olive":9,"onion":6} |
| topping_placement | 종류별 영역. {"olive":"left","onion":"right"} |
| bake | normal은 오븐 1회, well_done은 2회. 굽기 전 상태는 null |
| cuts | 조각 수. 0은 자르지 않음 |

환경 상태에는 실제 재료와 수량을 기록합니다. A의 `any`는 조건 표현이므로 T와 환경 상태에서는 구체적인 소스 종류를 사용합니다. 재료가 없으면 종류 목록과 수량·영역 객체는 비워 둡니다. 치즈가 없으면 `cheese_placement`는 적용하지 않습니다.

A의 `toppings`가 있으면 종류가 정확히 일치해야 합니다. 목록 생략은 종류 자유, 빈 목록은 토핑 없음입니다. 위치 객체에 적힌 재료의 위치만 채점합니다.

### 두 소스와 두 토핑의 영역·수량

왼쪽 토마토 소스·치즈·올리브 9개, 오른쪽 페스토 소스·양파 6개를 요구하는 피자 한 판의 조건입니다.

```json
{
  "sauce": ["tomato", "pesto"],
  "sauce_placement": {"tomato": "left", "pesto": "right"},
  "cheese": true,
  "cheese_placement": "left",
  "toppings": ["olive", "onion"],
  "topping_counts": {"olive": 9, "onion": 6},
  "topping_placement": {"olive": "left", "onion": "right"}
}
```

### 반반과 수량

- `left`와 `right`는 같은 피자 좌표계를 사용합니다. 방향 없는 반반은 해당 A 피자에 `allow_half_swap: true`를 기록해 소스·치즈·토핑의 일관된 좌우 교환을 허용합니다.
- A의 종류별 정수 수량은 정확히 비교합니다. 요구된 토핑의 수량이 생략되면 종류마다 1개 이상을 허용합니다. 별도 채점 최대값은 두지 않으며 실행은 S의 재고를 따릅니다.
- 전체 수량 조건은 `topping_count`에 기록합니다. 실제 전체 수량은 `topping_counts`를 합산합니다.
- 수량 범위는 `{"olive":{"min":1,"max":9}}`, 반쪽별 수량은 `{"olive":{"left":9,"right":3}}`으로 표현합니다. 상태에는 실제 정수 수량을 기록하며, 반쪽별 수량의 총합은 두 값을 더합니다.
- 조각별 균등 분포는 필수 조건으로 두지 않습니다.

## T: 행동 계획

T는 배열이며 각 항목은 `tool`과 `args`로 구성합니다. `args`에는 대상 피자 ID와 실제 실행할 인자를 기록합니다. Planning은 초기 S와 A를 고려해 이 순서와 인자를 정합니다.

참조 T와 다른 순서도 실행 가능하고 A를 만족하며 제출을 완료하면 통과합니다. Tool Use의 독립 평가에서는 제공한 T의 대상·인자·순서를 실제 호출이 수행했는지도 확인합니다.

예시: [T](../schemas/Q-SLATE/tool_calling_schema.json). 현재 환경의 도구와 선행 조건: [모의 게임](mock_game.md).

## E: 실행 기록과 최종 상태

E는 `trace`와 `final_state`로 구성합니다. `trace`는 도구 이름·인자·성공 여부·오류를 담고, `final_state`는 실행이 끝난 환경 상태를 S와 같은 형식으로 담습니다.

참조 E는 참조 T를 실행해서 생성합니다. 모델 실행의 E도 환경에서 수집합니다. 결과의 요구조건 충족은 정답 A로 판단합니다. 참조 E와 재고·자유 속성까지 모두 같을 필요는 없습니다.

예시: [E](../schemas/Q-SLATE/execution_schema.json).

## 특수 조건과 재료 확장

| A의 추가 필드 | 예시 |
| --- | --- |
| cheese_to_edge | true: 치즈를 테두리까지 적용 |
| pattern | "animal": 토핑으로 동물 그림 만들기 |
| extras | ["ring"]: 반지 등 추가 물품, ["sugar"]: 별도 첨가물 |
| box | "we_are_engaged": 지정된 포장 상자 ID |

명시적으로 요청된 조건만 해당 피자에 추가합니다. 이 조건을 평가하려면 대응하는 도구와 관측·채점 기능이 필요합니다. 현재 환경은 지원하지 않는 A 필드를 채점 오류로 표시합니다.

이벤트 재료도 같은 종류·수량·영역 구조로 표현하며, 실행 환경에는 해당 재료를 등록합니다. “모든 고기” 같은 범주는 문항에서 사용 가능한 재료를 기준으로 A에 펼칩니다. 추가 토핑을 허용하면서 오리만 요구하려면 `toppings`를 생략하고 `topping_counts`에 `{"duck":{"min":1}}`을 기록합니다.

## 원문과 검수

아래 공개 위키의 주문 목록에서 이전 형식의 샘플 주문을 수집했습니다. 소스 반반, 치즈와 소스의 독립 영역, 토핑별 영역과 수량, 여러 판 주문을 구조화한 뒤 원문과 대조합니다.

원문: [영어 주문 목록](https://good-pizza-great-pizza.fandom.com/wiki/List_of_orders), [이벤트 주문 아카이브](https://good-pizza-great-pizza.fandom.com/wiki/List_of_orders/Archive).

기본 선택값과 채점 원칙은 [README](../README.md), 재료·수량·영역의 의미는 [피자 제작 조건](pizza_domain_rules.md)을 따릅니다.
