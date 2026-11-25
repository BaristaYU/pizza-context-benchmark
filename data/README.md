# 데이터 파일 안내

## 영어 100문항

평가에 쓰는 표본이다. 같은 ID(`en100_001`부터 `en100_100`)로 Q, S, L, A, T, E가 연결돼 있다.

| 파일 | 내용 |
| --- | --- |
| `english100/benchmark_cases.jsonl` | 문항별 Q, S, L, A, T, E, 위키 출처(`source`), 검수 기록, 구조 난이도와 이해 난이도 |
| `english100/questions.jsonl` | Q 100건 |
| `english100/inputs/*.jsonl` | 단계별 Task가 모델에게 주는 입력. 파일마다 100줄 |
| `english100/validation.json` | 참조 실행 결과 요약 |
| `english100/manifest.json` | 데이터 버전, 환경 버전, 참조 기본값, 작성 원칙 |
| `english100/selection.json` | 문항을 뽑은 규칙, 구조 난이도별 후보 수, 제외한 위키 주문과 이유, 교체에 쓸 예비 주문 |
| `wiki/gpgp_wiki_orders.json` | 위키의 주문 목록과 Recipe Book. 문항 선정과 정답의 원본([안내](wiki/README.md)) |
| `menu.json` | 이름 붙은 피자 20종의 구성과 토핑 범주 15종. 위키를 따르며, 모델과 사람에게 같은 메뉴로 제공 |

`scripts/select_english100.py`가 위키 데이터에서 문항을 뽑아 Q, 출처, A, 검수 기록을 쓰고, 나머지는 `python -m pizzabench.english100`이 다시 만든다. Q는 위키의 주문 문장과 재확인 문장이고, A는 그 주문의 위키 레시피에 주문이 요구한 커팅과 두 번 굽기를 더한 것이다. 생성된 파일을 직접 고치지 말고, 작성한 값을 고친 뒤 이 명령을 실행한다. 테스트가 저장된 파일과 다시 만든 파일이 같은지 확인한다. L의 형식은 [L 주문서 형식](../docs/linguistics_form.md)을 따른다.

## 이전 형식의 샘플

`samples/question_fixed_recipes.jsonl`은 주문 원문 10건이고, `samples/benchmark_cases_fixed_recipes.jsonl`은 이 주문에 이전 환경(버전 `0.2`)의 상태, 정답, 계획, 실행 결과를 붙인 10문항이다. `schemas/`의 예시와 주문 채점기 테스트가 이 샘플을 사용한다. 현재 평가 데이터는 아니다.
