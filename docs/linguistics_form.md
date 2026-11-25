# L 주문서 형식 (l-form-v3)

L은 손님의 주문서이고, A는 요리사가 주문서를 보고 만드는 레시피다. 키오스크나 배달 앱에서 옵션을 체크한 주문서처럼, L은 모든 주문이 함께 쓰는 하나의 객관식 문항지에 true나 false를 채워 작성한다. 문항마다 정답 키가 따로 있는 방식이 아니므로, 같은 키 목록으로 100문항을 모두 표현한다. 모델이 L만 보고 A를 만들 수 있어야 하며, 맥락을 적는 자유 문장 필드는 두지 않는다.

정의와 검증, 비교는 `pizzabench/linguistics_form.py`에 있다.

## 구조

```json
{
  "pizzas": [
    {
      "wheat_dough": false, "bake_twice": false, "slices_2": false, "slices_4": false,
      "slices_8": false, "slices_18": false, "no_cut": false,
      "half_and_half": true,
      "sides": [
        {"category_fruits": true, "mushroom": true, "pepperoni": false, "...": false},
        {"category_meats": true, "pepperoni": false, "...": false}
      ]
    }
  ]
}
```

최초 주문만 읽은 `initial`과 재확인 문장까지 읽은 `clarified`가 같은 형식을 쓴다.

| 단위 | 선택지 | 개수 |
| --- | --- | --- |
| 피자 | 밀 도우, 두 번 굽기, 2조각, 4조각, 8조각, 18조각, 자르지 않기, 반반 | 8 |
| 면 | 소스(토마토, 페스토, 소스 빼기), 치즈 빼기 | 4 |
| 면 | 토핑 추가 | 28 |
| 면 | 빼기(토핑 10개, 해산물 전부, 채소 전부) | 12 |
| 면 | 범주 전체 | 15 |
| 면 | 이름 붙은 레시피 | 20 |

반반이 아닌 피자는 면 하나만 채우고, 반반 피자만 면 두 개를 채운다. 100문항의 141판 중 반반은 29판이라 대부분 선택지 한 벌만 채운다.

범주와 이름 붙은 레시피는 [메뉴](../data/menu.json)에 있는 것과 같다. 위키의 일반 주문(고정, 이름 붙은, 범주 레시피)은 모두 이 문항지로 적을 수 있으며, `tests/test_wiki_orders.py`가 위키 레시피마다 재료 단위의 L을 만들어 같은 A가 나오는지 확인한다.

## 작성 규칙

- 소스와 치즈는 기본으로 들어간다. 손님이 소스를 콕 집어 말할 때만 `tomato_sauce`나 `pesto_sauce`를, 빼달라고 할 때만 `no_sauce`, `no_cheese`를 체크한다. flatbread나 빵만은 소스와 치즈 없음이다. 체크하지 않은 토핑, 범주, 레시피는 넣지 않는다.
- 이름 붙은 레시피와 범주는 그대로 체크하고 재료로 펼치지 않는다. 손님이 재료를 따로 말하면 그 재료도 체크한다.
- 조각 수(`slices_2`, `slices_4`, `slices_8`, `slices_18`, `no_cut`)와 소스(`tomato_sauce`, `pesto_sauce`, `no_sauce`)는 단일 선택이다. 각각 하나까지만 참이고, 모두 거짓이면 기본값(6조각, 아무 소스)이다. `validate`가 둘 이상 체크한 답을 형식 오류로 처리하며, 작성 도구는 라디오 버튼으로 보여 준다. 레시피의 소스를 바꾸는 주문은 바꾼 소스 하나만 체크한다.
- "햄 대신 오리"는 오리와 `no_ham`이다.
- 모든 값은 true나 false이며 숫자 필드는 없다. 판수는 피자 주문서의 장수로 표현한다. 계산이 필요한 주문도 계산을 마친 판수만큼 적으므로, "4조각짜리로 12명에게 한 조각씩"은 주문서 3장이다.
- 반반 피자에서 어느 쪽이 먼저인지는 상관없고, 피자 전체에 해당하는 것은 두 면 모두에 체크한다.
- 다른 사람의 취향이나 잡담은 적지 않는다.

## 초안과 Ground Truth

assistant가 100문항의 `initial`과 `clarified`를 작성한 초안은 `pizzabench/english100_linguistics.py`에 있고, 데이터 생성 시 `benchmark_cases.jsonl`의 `linguistics`로 들어간다. 초안은 위키 데이터 안의 위치(`source.wiki_key`)로 문항과 연결된다. 테스트는 `clarified` 초안이 메뉴를 거쳐 그 문항의 A와 같은 정답으로 이어지는지 확인한다(`pizzabench/l_to_a.py`). 초안은 정답이 아니며, 팀원의 독립 작성 결과와 비교해 Ground Truth를 정한다.

팀원은 초안과 정답을 보지 않는 작성 도구로 문항지를 푼다. 도구는 Python만 설치되어 있으면 추가 설치 없이 실행되는 파일 하나이며, 다음 명령으로 만든다.

```powershell
py scripts/build_l_annotator.py --output ..\L_annotator
```

만들어진 `L_annotator.zip`을 보내면 된다. 압축을 풀고 `실행하기.bat`을 더블클릭해 이름을 적고 시작한다. 문항마다 손님의 첫 말만 듣고 ① 첫 주문서를 작성하고, "네?"를 눌러 다시 들은 말이 나타나면 ② 주문서를 작성한다. ②는 ①의 내용에서 시작한다. 이해 난이도(하, 중, 상)는 ① 첫 말만 들었을 때와 ② 다시 들은 뒤를 따로 고르고 "저장하고 다음"을 누른다. 문항은 드롭다운에서 고른다.

문항 순서는 문항 번호를 따른다. 번호는 구조 난이도 하, 중, 상을 번갈아 붙였으므로 1~50번과 51~100번에 구조 난이도가 고르게 나뉜다. 두 팀원이 50문항씩 나누어 작성하며 팀원 간 일치도는 재지 않는다. 난이도는 도구에 보이지 않는다.

결과는 도구 폴더의 `L_결과_<이름>.json` 하나에 저장된다. "저장하고 다음"으로 끝낸 문항은 `answers`에 들어가고, 작성 중인 문항은 다른 문항으로 옮길 때, 창을 닫을 때, 30초마다 `drafts`에 들어간다. 파일은 임시 파일에 쓴 뒤 바꿔치기하므로 저장 도중 꺼져도 이전 내용이 남는다. 같은 이름으로 다시 시작하면 작성 중이던 문항, 없으면 아직 안 한 첫 문항을 연다. 드롭다운에는 문항마다 완료나 작성 중이 표시된다.

```json
{"format": "l-annotation-v2", "form_version": "l-form-v3", "annotator": "<이름>",
 "answers": {"<case id>": {"number": 1, "initial": {"pizzas": []}, "clarified": {"pizzas": []},
                           "difficulty": {"initial": "상", "clarified": "하"}, "saved_at": "..."}},
 "drafts": {}}
```

받은 결과 파일은 `data/english100/l_annotations/`에 두고 초안과 비교한다. `drafts`는 비교에 쓰지 않는다.

```powershell
py scripts/compare_linguistics.py data/english100/l_annotations/L_결과_*.json --output l_review.md
```

보고서에는 단계별 완전 일치 비율, 가장 자주 갈린 선택지, 갈린 문항마다 다른 선택지, 단계별 이해 난이도 분포, ①에서 ②로 바뀐 난이도 표, 구조 난이도와 이해 난이도(①)의 교차표가 나온다. `--write-difficulty`를 붙이면 팀원이 고른 이해 난이도를 문항 데이터의 `question.difficulty.lcs`에 저장한다.

## 난이도

난이도는 두 축으로 나눈다. 이해 난이도는 주문을 알아듣기 어려운 정도로, 팀원이 ①과 ②에서 각각 하, 중, 상을 고른다. 구조 난이도(OCS)는 만들 피자가 복잡한 정도로, `pizzabench/structure_difficulty.py`가 A에서 계산한다. 판수, 반반 분할, 토핑 수, 기본이 아닌 슬롯, 서로 다른 피자의 다섯 항목을 0~2점으로 매겨 합하고, 합이 0~1이면 하, 2~3이면 중, 4 이상이면 상이다. 100문항은 위키 주문 중에서 구조 난이도 하 33, 중 33, 상 34로 뽑았다.

문항마다 `question.difficulty`에 두 난이도를 함께 저장한다. `ocs`, `ocs_level`, `ocs_raw`, `ocs_breakdown`은 A에서 계산한 구조 난이도이고, `lcs`의 `initial`과 `clarified`는 팀원이 고른 이해 난이도로 라벨을 저장하기 전에는 null이다. 이해 난이도의 비율이 크게 치우치면 문항을 예비 주문으로 바꿔 조정한다. 예비 주문은 `data/english100/selection.json`에 구조 난이도별로 뽑힌 순서대로 있다.

```powershell
py scripts/select_english100.py --drop 12:0 --reason "이해 난이도 하가 많아 교체"
```

빠진 문항의 번호는 같은 구조 난이도의 다음 예비 주문이 이어받고, 다른 문항의 번호와 저장된 라벨은 그대로 남는다. 새 문항의 L 초안을 쓴 뒤 `python -m pizzabench.english100`으로 데이터를 다시 만든다.

## 채점

`compare(expected, actual)`은 피자의 순서와 반쪽의 순서를 무시하고 모든 선택지가 같은지 본다. 하나라도 다르면 실패이며, 다른 선택지 목록을 함께 돌려준다. 형식이 틀린 답은 형식 오류로 따로 기록한다. NLU 평가의 통과 여부와 실패 분석 리포트에 그대로 쓴다.
