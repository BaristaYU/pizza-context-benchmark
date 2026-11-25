"""Read-only Korean explanations of errors already recorded by the evaluator.

These labels are presentation metadata: they never run grading, repair tool calls,
change the model conversation or decide whether an execution passes.
"""


def _item(category, title, detail):
    return {'category': category, 'title': title, 'detail': detail}


def _api_diagnostic(report):
    code = report.get('error_code')
    text = str(report.get('error') or '').lower()
    if code == 429 or '할당량' in text or 'quota' in text or 'rate limit' in text:
        return _item('api_quota', 'API 사용 한도',
                     '서비스가 사용 한도 오류를 반환했습니다. 요청·토큰·일일 할당량 중 어떤 한도인지는 서비스의 원본 기록에서 확인해야 합니다.')
    if code in (401, 403) or '인증' in text or 'api key' in text:
        return _item('api_auth', 'API 인증·권한',
                     '서비스의 인증 또는 사용 권한 오류가 기록되어 있습니다. 로컬 키 설정과 계정 권한을 확인하세요.')
    if code == 404 or '모델을 찾을' in text or 'model not found' in text:
        return _item('api_model', 'API 모델 사용 불가',
                     '선택한 모델 또는 API 경로를 사용할 수 없다는 오류가 기록되어 있습니다. 다른 모델을 자동 선택하지는 않습니다.')
    if any(word in text for word in ('network', 'timeout', 'timed out', '네트워크', '대기 30초', '연결 오류')):
        return _item('api_network', 'API 연결·응답 대기',
                     '연결 또는 응답 대기 오류가 기록되어 제작을 끝내지 못했습니다. 제작 조건 오류와 구분해서 확인하세요.')
    return _item('api_request', 'API 요청 오류',
                 '서비스 요청이 정상 완료되지 않았습니다. 이 분류만으로 모델의 주문 이해 실패라고 판단하지 않습니다.')


def _record_diagnostic(error):
    text = error.lower()
    if any(value in text for value in ('unsupported a field', 'disagrees with e.pizzas', 'no one-to-one', 'no complete a alternative', 'a.alternatives is empty')):
        return _item('other', '기타 채점·데이터 기록',
                     '피자 대응 관계 또는 지원 조건에 관한 채점 오류가 기록되어 있습니다. 구체적인 원본 오류를 확인하세요.')
    if any(value in text for value in ('not been fully submitted', 'must be submitted', 's.submitted disagrees')):
        return _item('submission', '제출 조건 미충족',
                     '모든 피자의 제출 완료 조건을 만족하지 못했다는 기록입니다.')
    if any(value in text for value in ('_placement', 'region must be', 'wrong or absent cheese region', 'initial sauce or region')):
        return _item('location', '재료 위치·영역 확인',
                     '재료의 전체·반쪽·좌우 위치 또는 영역 인자가 요구조건과 맞지 않는다는 기록입니다.')
    if any(value in text for value in ('topping_count', 'requires at least one piece', 'count must be', 'pizza_count: expected', 'cuts: expected', 'slices must be', 'insufficient ')):
        return _item('quantity', '수량·조각 수 확인',
                     '토핑 개수·피자 수·조각 수 또는 재고 수량에 관한 오류가 기록되어 있습니다.')
    if any(value in text for value in ('toppings: missing', 'sauce: expected', 'cheese: expected', 'dough: expected', 'unavailable ', 'item must be')):
        return _item('ingredient', '재료 종류·포함 여부 확인',
                     '도우·소스·치즈·토핑의 종류나 포함 여부가 요구조건 또는 사용 가능한 재료와 맞지 않는다는 기록입니다.')
    if any(value in text for value in ('before ', 'must precede', 'follow sauce', 'already ', 'has no dough', 'bake: expected', 'oven passes', 'requires exactly', 'missing arguments', 'unknown arguments', 'unknown tool', 'args must be', 'invalid argument', 'pizza must be a positive integer')):
        return _item('order', '제작 순서·호출 인자 확인',
                     '제작의 선행 순서 또는 도구 호출 인자가 올바르지 않았다는 기록입니다.')
    return _item('other', '분류되지 않은 오류 기록',
                 '기존 오류 기록이 있으나 정해진 분류에 해당하지 않습니다. 새로운 실패 원인을 추정하지 않고 원본 오류를 유지합니다.')


def diagnose(report):
    """Return category/title/detail explanations without modifying any input.

    API and final grading evidence stay separate. A recovered tool error remains
    visible as an intermediate event even when the final evaluator passed.
    """
    if not isinstance(report, dict):
        return []
    result = []
    if report.get('termination') == 'api_error' or report.get('error_code') is not None:
        result.append(_api_diagnostic(report))
    score = report.get('score') or {}
    if not isinstance(score, dict):
        score = {}
    seen = set()
    for error in score.get('errors') or []:
        if not isinstance(error, str) or error in seen:
            continue
        seen.add(error)
        result.append(_record_diagnostic(error))
    tool_errors = []
    for record in report.get('records') or []:
        if isinstance(record, dict) and isinstance(record.get('response'), dict):
            tool_errors.append(record['response'].get('error'))
    execution = report.get('execution') or {}
    if isinstance(execution, dict):
        for entry in execution.get('trace') or []:
            if isinstance(entry, dict):
                tool_errors.append(entry.get('error'))
    for error in tool_errors:
        if not isinstance(error, str) or error in seen:
            continue
        seen.add(error)
        item = _record_diagnostic(error)
        item['detail'] = '제작 중 도구 오류 기록입니다. ' + item['detail']
        if score.get('passed') is True:
            item['detail'] += ' 이후 최종 채점은 성공했습니다.'
        result.append(item)
    return result
