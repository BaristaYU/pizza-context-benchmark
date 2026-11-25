"""Compare real saved runs without mixing cohorts or latest and cumulative data."""
from datetime import datetime
from html import escape
from urllib.parse import urlsplit


def compare_summaries(summaries):
    if not summaries:
        raise ValueError('비교할 summary.json이 하나 이상 필요합니다.')
    indexed = []
    for summary in summaries:
        rows = summary.get('rows')
        if not isinstance(rows, list):
            raise ValueError('summary.json의 rows 목록이 없습니다.')
        by_id = {row['case_id']: row for row in rows}
        if len(by_id) != len(rows):
            raise ValueError('한 실행 안에 중복 문항 ID가 있습니다.')
        indexed.append(by_id)
    selected = [set(rows) for rows in indexed]
    finished = [{case_id for case_id, row in rows.items() if row.get('termination') == 'finished'} for rows in indexed]
    common_selected = sorted(set.intersection(*selected))
    common_completed = sorted(set.intersection(*finished))
    fingerprints = [summary.get('dataset_fingerprint') or summary.get('run_manifest', {}).get('dataset_fingerprint') for summary in summaries]
    control_fingerprints = [summary.get('control_fingerprint') or summary.get('run_manifest', {}).get('control_fingerprint') for summary in summaries]
    warnings = []
    if len(summaries) < 2:
        warnings.append('실제 실행 자료가 1개뿐입니다. 다른 모델과의 성능 비교는 아직 할 수 없습니다.')
    if any(cohort != selected[0] for cohort in selected[1:]):
        warnings.append('선택한 문항 구성이 서로 다릅니다. 전체 실행 성공률의 분모가 다르므로 단순 순위를 매기지 않습니다.')
    if not all(fingerprints):
        warnings.append('문항 데이터 해시가 없는 실행이 있습니다. 같은 ID의 실제 정답·초기 상태가 같은지 증명할 수 없습니다.')
    elif len(set(fingerprints)) != 1:
        warnings.append('문항 데이터 해시가 다릅니다. 선택 범위 또는 내용이 다를 수 있으므로 공정한 공통 성능 지표를 산출하지 않습니다.')
    if not all(control_fingerprints):
        warnings.append('통제변수 지문이 없는 실행이 있습니다. 같은 프롬프트·도구·환경·채점·생성 설정·요청 간격·예산인지 증명할 수 없어 공통 성능을 산출하지 않습니다.')
    elif len(set(control_fingerprints)) != 1:
        warnings.append('통제변수 지문이 다릅니다. 데이터 외 프롬프트·도구·환경·채점·생성 설정·간격·예산도 같아야 공정 비교할 수 있습니다.')
    # The control fingerprint covers shared experiment conditions; service settings stay visible.
    service_fingerprints = [summary.get('service_fingerprint') or summary.get('run_manifest', {}).get('service_fingerprint') for summary in summaries]
    if len(summaries) >= 2 and len(set(service_fingerprints)) > 1:
        warnings.append('서비스별 API·생성 설정이 다릅니다. 프롬프트·도구·환경·채점·예산은 같아도 생성 옵션 차이를 함께 해석하세요. 각 실행의 model_settings를 확인할 수 있습니다.')
    if not common_selected:
        warnings.append('모든 실행에 공통으로 선택된 문항이 없습니다.')
    if not common_completed:
        warnings.append('모든 실행에서 완료 선언까지 도달한 공통 문항이 없습니다. 공통 완료 성공률은 0%가 아니라 산출 불가입니다.')
    comparable = len(summaries) >= 2 and all(fingerprints) and len(set(fingerprints)) == 1 and bool(common_completed) and all(control_fingerprints) and len(set(control_fingerprints)) == 1
    runs = []
    for summary, rows in zip(summaries, indexed):
        values = list(rows.values())
        attempted = sum(row.get('termination') != 'not_run' for row in values)
        completed = sum(row.get('termination') == 'finished' for row in values)
        passed = sum(row.get('termination') != 'not_run' and bool(row.get('passed')) for row in values)
        common_passed = sum(bool(rows[case_id].get('passed')) for case_id in common_completed)
        cumulative_tokens = summary.get('cumulative_tokens', summary.get('tokens', {}))
        if isinstance(cumulative_tokens, dict): cumulative_tokens = cumulative_tokens.get('total', 0)
        runs.append({'provider': summary.get('provider', summary.get('model_settings', {}).get('provider', 'unknown')),
                     'model': summary.get('model', 'unknown'), 'source_directory': summary.get('source_directory'),
                     'report_href': summary.get('report_href'), 'selected': len(values), 'attempted': attempted,
                     'completed': completed, 'passed': passed,
                     'api_errors': sum(row.get('termination') == 'api_error' for row in values),
                     'not_run': len(values)-attempted,
                     'latest_success_rate_attempted': passed/attempted if attempted else None,
                     'common_completed': len(common_completed), 'common_completed_passed': common_passed,
                     'common_completed_success_rate': common_passed/len(common_completed) if comparable else None,
                     'cumulative_requests': summary.get('cumulative_requests', summary.get('requests', 0)),
                     'cumulative_tokens': cumulative_tokens,
                     'cumulative_elapsed_seconds': summary.get('cumulative_elapsed_seconds', summary.get('elapsed_seconds', 0)),
                     'attempt_records': summary.get('attempt_records', attempted),
                     'control_fingerprint': summary.get('control_fingerprint'), 'dataset_fingerprint': summary.get('dataset_fingerprint'),
                     'service_fingerprint': summary.get('service_fingerprint'), 'model_settings': summary.get('model_settings', {}),
                     'cumulative_cost_usd': summary.get('cumulative_cost_usd')})
    return {'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'run_count': len(runs), 'common_selected_case_ids': common_selected,
            'common_completed_case_ids': common_completed, 'comparable': bool(comparable),
            'warnings': warnings, 'runs': runs}


def render_comparison(comparison):
    def esc(value): return escape(str(value), quote=True)
    def pct(value): return '산출 불가' if value is None else f'{value*100:.1f}%'
    rows = []
    for run in comparison['runs']:
        model = esc(run['model'])
        href = run.get('report_href')
        # Only CLI-generated relative paths or file/http links can become links.
        if href and urlsplit(str(href)).scheme.lower() in {'', 'file', 'http', 'https'}:
            model = f'<a href="{esc(href)}">{model}</a>'
        rows.append(f'''<tr><td><strong>{esc(run['provider'])}</strong><small>{model}</small></td>
<td>{run['selected']} / {run['attempted']} / {run['completed']}</td>
<td>{run['passed']} / {run['attempted']}<small>{pct(run['latest_success_rate_attempted'])}</small></td>
<td>{run['api_errors']}<small>미실행 {run['not_run']}</small></td>
<td>{pct(run['common_completed_success_rate'])}<small>성공 {run['common_completed_passed']} / 공통 완료 {run['common_completed']}</small></td>
<td>{run['cumulative_requests']:,}<small>시도 이력 {run['attempt_records']}</small></td>
<td>{run['cumulative_tokens']:,}</td><td>{run['cumulative_elapsed_seconds']:.2f}초</td><td>{'—' if run.get('cumulative_cost_usd') is None else f"${run['cumulative_cost_usd']:.4f}"}</td></tr>''')
    warnings = ''.join(f'<li>{esc(warning)}</li>' for warning in comparison['warnings'])
    ids = ' · '.join(esc(value) for value in comparison['common_completed_case_ids']) or '없음'
    validity = '같은 데이터와 통제변수에서 완료된 공통 문항 지표를 산출했습니다. 모델은 비교 변수이며 서비스 계정별 한도 차이는 별도로 해석해야 합니다.' if comparison['comparable'] else '현재 자료로 공정한 공통 완료 성능을 비교할 수 없습니다.'
    return f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PizzaBench · 실제 모델 실행 비교</title><style>
body{{margin:0;background:#f3f5fa;color:#26344c;font:15px/1.7 "Malgun Gothic",sans-serif}}main{{max-width:1380px;margin:auto;padding:40px 28px}}h1{{font-size:32px;margin:7px 0}}h2{{font-size:22px;margin:10px 0}}p,small{{color:#66738a}}small{{display:block;font-size:12px}}.eyebrow{{color:#5264ad;font-weight:bold;letter-spacing:1px}}section,.card{{background:white;border:1px solid #dfe5ef;border-radius:14px;padding:22px;margin:22px 0}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.card{{margin:0}}.card strong{{display:block;font-size:30px}}table{{width:100%;border-collapse:collapse;text-align:left;font-size:13px}}th,td{{padding:15px 10px;border-bottom:1px solid #e5eaf2;vertical-align:top}}th{{background:#edf1f8;white-space:nowrap}}.scroll{{overflow:auto}}a{{color:#355b8e}}.note{{border-left:3px solid #dbac64;padding-left:15px}}code{{background:#f0f3f8;padding:2px 4px}}@media(max-width:760px){{main{{padding:24px 14px}}.cards{{grid-template-columns:1fr}}}}</style>
<main><div class="eyebrow">PIZZA CONTEXT BENCHMARK / OBSERVED RUNS</div><h1>서비스·모델 실행 비교</h1>
<p>{esc(comparison['created_at'])} · 실제 저장된 실행만 포함하며 새로운 API 요청을 보내지 않습니다.</p>
<div class="cards"><div class="card"><small>실제 실행 자료</small><strong>{comparison['run_count']}개</strong></div>
<div class="card"><small>모든 실행의 공통 선택 문항</small><strong>{len(comparison['common_selected_case_ids'])}개</strong></div>
<div class="card"><small>모든 실행의 공통 완료 문항</small><strong>{len(comparison['common_completed_case_ids'])}개</strong></div></div>
<section><h2>비교 가능 여부</h2><p class="note">{validity}</p>{'<ul>'+warnings+'</ul>' if warnings else '<p>문항 데이터 해시와 공통 완료 문항을 확인했습니다. 단일 실행 결과이므로 모델의 일반 성능 순위로 해석하지 않습니다.</p>'}</section>
<section><h2>실행 결과 표</h2><div class="scroll"><table><thead><tr><th>서비스 / 모델</th><th>선택 / 시도 / 완료</th><th>최근 성공 / 시도</th><th>최근 API 오류</th><th>공통 완료 성공률</th><th>누적 요청</th><th>누적 토큰</th><th>누적 시간</th><th>추정 비용</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section><h2>집계 기준</h2><p>최근 성공률은 문항별 최신 결과에서 성공 ÷ 시도를 계산합니다. API 오류는 제작 조건 미충족과 구분하며 미실행 문항은 시도 분모에 넣지 않습니다. 선택·시도·완료 수가 다르면 각 실행 전체의 성공률을 단순 비교하지 마세요.</p>
<p>공통 완료 성공률은 모든 실행에서 완료 선언한 동일 문항 집합을 같은 분모로 사용합니다. 데이터 해시가 같고 두 개 이상의 실행이 있을 때만 표시합니다. 해시가 없거나 다르거나 공통 완료 문항이 없으면 산출 불가로 표시합니다. 공통 완료 집합은 중도 오류가 난 문항을 제외하므로 전체 선택 문항 성능을 대신하지 않습니다.</p>
<p>누적 요청·토큰·시간은 summary에 기록된 이전 재개 시도까지 포함합니다. 누적 사용량이 없는 예전 자료는 당시 최근 집계값을 사용합니다. 서버가 사용량을 주지 않은 요청은 토큰 수에서 누락될 수 있으며 토큰 수는 청구 금액이 아닙니다.</p>
<p>공통 완료 문항: <code>{ids}</code></p><p>원본 모델별 보고서는 모델명 링크로 확인하세요. 원본 결과 폴더와 이 비교 폴더를 함께 보관해야 상대 링크가 유지됩니다.</p></section></main></html>'''
