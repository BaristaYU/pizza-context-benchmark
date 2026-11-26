"""Aggregate actual executions into a portable, escaped Korean HTML report."""
from collections import Counter
from datetime import datetime
from html import escape
import json
from .diagnostics import diagnose

STATUS = {'finished': '제작 완료', 'api_error': 'API 오류', 'not_run': '미실행',
          'request_limit': '요청 제한', 'tool_limit': '도구 제한', 'time_limit': '시간 제한',
          'tool_error_limit': '도구 오류 반복', 'cancelled': '중지', 'cost_limit': '비용 한도'}


def token_counts(usage):
    # 'input'/'output'/'total' come from the kitchen runner, which normalises every service.
    aliases = {'input': ('input', 'prompt_token_count', 'promptTokenCount'),
               'output': ('output', 'candidates_token_count', 'candidatesTokenCount'),
               'total': ('total', 'total_token_count', 'totalTokenCount')}
    counts = dict.fromkeys(aliases, 0)
    for entry in usage:
        for name, keys in aliases.items():
            counts[name] += next((entry[k] for k in keys if isinstance(entry.get(k), (int, float))), 0)
    return counts


def summarize(cases, results, model, *, task='E2E'):
    by_id = {case['id']: case for case in cases}
    rows = []
    for report in results:
        case = by_id[report['case_id']]
        question = case.get('question') or {}
        termination = report['termination']
        attempted = termination != 'not_run'
        passed = attempted and bool((report.get('score') or {}).get('passed'))
        records = report.get('records', [])
        # OCS/LCS annotations are objects; cases without them report no difficulty.
        raw_difficulty = question.get('difficulty')
        difficulty = raw_difficulty if isinstance(raw_difficulty, dict) else {}
        attempts = report.get('attempts') or ([report] if attempted else [])
        cumulative_tokens = token_counts([usage for attempt in attempts for usage in attempt.get('usage', [])])
        cost = (report.get('cost') or {}).get('total_usd')
        attempt_costs = [(attempt.get('cost') or {}).get('total_usd') for attempt in attempts]
        rows.append({'case_id': case['id'], 'language': question.get('language', 'unknown'),
            'order_text': question.get('order_text', ''), 'difficulty': difficulty,
            'termination': termination, 'attempted': attempted, 'passed': passed,
            'requests': report.get('requests', 0), 'elapsed_seconds': round(report.get('elapsed_seconds', 0), 2),
            'tokens': token_counts(report.get('usage', [])),
            'attempt_count': len(attempts), 'cumulative_tokens': cumulative_tokens,
            'cumulative_requests': sum(a.get('requests', 0) for a in attempts),
            'cumulative_elapsed_seconds': round(sum(a.get('elapsed_seconds', 0) for a in attempts), 2),
            'tool_calls': sum('tool' in r for r in records),
            'tool_errors': sum('error' in r.get('response', {}) for r in records),
            'clarification_requested': any(r.get('tool') == 'clarify' for r in records),
            'error': report.get('error'), 'error_code': report.get('error_code'),
            'grading_errors': (report.get('score') or {}).get('errors', []), 'diagnostics': diagnose(report),
            'cost_usd': cost,
            'cumulative_cost_usd': round(sum(c for c in attempt_costs if c is not None), 6) if any(c is not None for c in attempt_costs) else None,
            'result_file': case['id']+'.json'})
        if task == 'Reasoning':
            rows[-1]['grading_status'] = (report.get('score') or {}).get('status')
    attempted = sum(r['attempted'] for r in rows)
    completed = sum(r['termination'] == 'finished' for r in rows)
    passed = sum(r['passed'] for r in rows)
    tokens = {key: sum(r['tokens'][key] for r in rows) for key in ('input', 'output', 'total')}
    groups = []
    for language in sorted({r['language'] for r in rows}):
        subset = [r for r in rows if r['language'] == language]
        groups.append({'language': language, 'selected': len(subset),
            'attempted': sum(r['attempted'] for r in subset), 'passed': sum(r['passed'] for r in subset)})
    summary = {'created_at': datetime.now().astimezone().isoformat(timespec='seconds'), 'model': model,
            'task': task, 'selected': len(rows), 'attempted': attempted, 'completed': completed,
            'passed': passed, 'grading_failed': sum(r['termination'] == 'finished' and not r['passed'] for r in rows),
            'api_errors': sum(r['termination'] == 'api_error' for r in rows),
            'not_run': len(rows)-attempted, 'termination_counts': dict(Counter(r['termination'] for r in rows)),
            'success_rate_completed': passed/completed if completed else None,
            'success_rate_attempted': passed/attempted if attempted else None,
            'requests': sum(r['requests'] for r in rows), 'elapsed_seconds': round(sum(r['elapsed_seconds'] for r in rows), 2),
            'tokens': tokens, 'language_groups': groups, 'rows': rows,
            'provider': next((r.get('provider') or str(r.get('model_settings', {}).get('provider', 'gemini')).lower() for r in results), 'gemini'),
            'attempt_records': sum(r['attempt_count'] for r in rows),
            'cumulative_tokens': {key: sum(r['cumulative_tokens'][key] for r in rows) for key in ('input', 'output', 'total')},
            'cumulative_requests': sum(r['cumulative_requests'] for r in rows),
            'cumulative_elapsed_seconds': round(sum(r['cumulative_elapsed_seconds'] for r in rows), 2),
            'model_settings': next((r.get('model_settings', {}) for r in results if r.get('model_settings')), {}),
            'limits': next((r.get('limits', {}) for r in results if r.get('limits')), {}),
            'cost_usd': round(sum(r['cost_usd'] or 0 for r in rows), 6),
            'cumulative_cost_usd': round(sum(r['cumulative_cost_usd'] or 0 for r in rows), 6),
            'cost_note': 'configs/agent_models.json의 공개 단가로 계산한 추정 금액이며 실제 청구서와 다를 수 있습니다.'}
    if task == 'Reasoning':
        statuses = Counter(row['grading_status'] for row in rows)
        valid = passed + statuses['condition_mismatch']
        summary.update(format_errors=statuses['format_error'], condition_mismatches=statuses['condition_mismatch'],
                       valid_answers=valid, success_rate_valid_answers=passed / valid if valid else None,
                       format_error_rate=statuses['format_error'] / completed if completed else None)
    return summary


def render_html(summary):
    def esc(value): return escape(str(value), quote=True)
    def percent(value): return '산출 불가' if value is None else f'{value*100:.1f}%'
    rows = []
    for row in summary['rows']:
        status = '성공' if row['passed'] else ('조건 미충족' if row['termination'] == 'finished' else STATUS.get(row['termination'], row['termination']))
        color = 'success' if row['passed'] else ('muted' if not row['attempted'] else 'warning')
        errors = ([row['error']] if row['error'] else []) + row['grading_errors']
        explanations='<br>'.join(esc(d['title']+': '+d['detail']) for d in row.get('diagnostics',[]))
        diagnostic_html=explanations or '—'
        if errors:diagnostic_html+='<details><summary>원본 오류</summary>'+ '<br>'.join(esc(e) for e in errors)+'</details>'
        rows.append(f'''<tr><td><a href="{esc(row['result_file'])}">{esc(row['case_id'])}</a><p>{esc(row['order_text'])}</p></td>
<td><span class="badge {color}">{esc(status)}</span><small>{esc(row['termination'])}</small></td>
<td>{row['requests']}<small>누적 {row['cumulative_requests']}회 · {row['attempt_count']}번 시도</small></td><td>{row['tool_calls']}<small>오류 {row['tool_errors']}회</small></td>
<td>{row['elapsed_seconds']:.2f}초</td><td>{row['tokens']['total']:,}<small>입력 {row['tokens']['input']:,} / 출력 {row['tokens']['output']:,}</small></td>
<td>{'요청함' if row['clarification_requested'] else '없음'}</td><td>{'—' if row.get('cost_usd') is None else f"${row['cost_usd']:.4f}"}</td><td>{diagnostic_html}</td></tr>''')
    groups = ''.join(f"<tr><td>{esc(g['language'])}</td><td>{g['selected']}</td><td>{g['attempted']}</td><td>{g['passed']}</td></tr>" for g in summary['language_groups'])
    difficulty_known = sum(bool(r['difficulty'].get('ocs')) or bool(r['difficulty'].get('lcs')) for r in summary['rows'])
    return f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PizzaBench · AI 실험 결과</title>
<style>body{{margin:0;background:#f4f6fa;color:#1f2937;font:15px/1.7 "Malgun Gothic",sans-serif}}main{{max-width:1440px;margin:auto;padding:42px 28px}}h1{{font-size:34px;line-height:1.3;margin:8px 0}}h2{{margin:32px 0 14px;font-size:22px}}p{{margin:8px 0;color:#596579}}.eyebrow{{color:#5364ba;font-weight:bold;letter-spacing:1px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:26px 0}}.card,section{{background:white;border:1px solid #e0e5ed;border-radius:14px;padding:22px}}.card strong{{display:block;font-size:30px;color:#263757}}.card span,small{{display:block;color:#66738a;font-size:12px}}section{{margin-bottom:20px}}.table{{overflow:auto}}table{{width:100%;border-collapse:collapse;text-align:left;font-size:13px}}td,th{{padding:13px 10px;vertical-align:top;border-bottom:1px solid #e6eaf0}}th{{background:#f4f6fb;white-space:nowrap;color:#45516b}}td:first-child{{min-width:235px}}td p{{font-size:12px;margin:5px 0}}a{{color:#344b9e}}.badge{{display:inline-block;border-radius:20px;padding:3px 10px;white-space:nowrap;font-weight:bold}}.success{{background:#e4f4ed;color:#217653}}.warning{{background:#fff0dc;color:#8b5d1d}}.muted{{background:#e9edf3;color:#58677b}}code{{font-size:12px;background:#f1f3f8;padding:2px 5px;border-radius:4px}}.note{{border-left:3px solid #7b8bd1;padding-left:14px}}@media(max-width:800px){{.cards{{grid-template-columns:repeat(2,1fr)}}main{{padding:24px 14px}}}}@media print{{body{{background:white}}main{{padding:0}}section{{break-inside:avoid}}}}</style>
<main><div class="eyebrow">PIZZA CONTEXT BENCHMARK / REAL API RUN</div><h1>AI 주문 제작 실험 결과</h1>
<p>서비스 {esc(summary.get('provider', 'gemini'))} · 모델 <strong>{esc(summary['model'])}</strong> · E2E · {esc(summary['created_at'])}</p>
<div class="cards"><div class="card"><span>성공 / 실제 시도</span><strong>{summary['passed']} / {summary['attempted']}</strong><span>선택 {summary['selected']}개 · 미실행 {summary['not_run']}개</span></div>
<div class="card"><span>시도 문항 기준 성공률</span><strong>{percent(summary['success_rate_attempted'])}</strong><span>성공 ÷ 실제 API 실행을 시도한 문항</span></div>
<div class="card"><span>완료 선언 문항 기준 성공률</span><strong>{percent(summary['success_rate_completed'])}</strong><span>성공 ÷ 완료 선언 {summary['completed']}개</span></div>
<div class="card"><span>이전 시도를 포함한 누적 사용량</span><strong>{summary.get('cumulative_tokens', summary['tokens'])['total']:,}</strong><span>토큰 · 요청 {summary.get('cumulative_requests', summary['requests'])}회 · {summary.get('cumulative_elapsed_seconds', summary['elapsed_seconds']):.2f}초 · 추정 ${summary.get('cumulative_cost_usd', 0):.4f}</span></div></div>
<section><h2>문항별 실제 실행</h2><p>문항 ID를 누르면 최신 문항 JSON과 attempts 이력을 확인할 수 있습니다. 성공률은 문항별 최신 결과 기준이며 누적 사용량은 이어 실행 전 실패 시도도 포함합니다. API 오류와 제작 조건 미충족을 구분합니다.</p><div class="table"><table><thead><tr><th>문항 / 고객 주문</th><th>결과</th><th>최근 AI 요청 / 누적</th><th>도구 호출</th><th>시간</th><th>최근 토큰</th><th>추가 설명</th><th>추정 비용</th><th>진단</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section><h2>데이터를 어떻게 묶었나요?</h2><div class="table"><table><tr><th>묶음</th><th>포함 데이터</th><th>역할과 모델 공개 범위</th></tr>
<tr><td>Q · 고객 주문</td><td>문항 ID, 언어, order_text, 추가 설명</td><td>주문은 모델 입력. 추가 설명은 clarify 요청 때만 공개합니다.</td></tr>
<tr><td>S · 초기 환경</td><td>재고·피자 상태·제출 여부</td><td>문항별 독립 복사본에서 시작합니다. 모델은 초기 상태와 관측 도구를 이용합니다.</td></tr>
<tr><td>A · 정답 제작 조건</td><td>허용 재료·수량·위치·굽기·조각 수</td><td>평가자 전용입니다. 최종 피자 채점에만 사용하며 모델에는 제공하지 않습니다.</td></tr>
<tr><td>L·T·참조 E</td><td>정답 문장 분석·참조 계획·참조 실행</td><td>검수용 원본입니다. 이번 E2E 모델 입력과 생성 결과로 취급하지 않습니다.</td></tr>
<tr><td>실제 도구 호출·E</td><td>모델 호출 인자·응답·오류·최종 환경</td><td>이번 API 실행에서 관측한 결과입니다. 모델이 성공했다고 말해도 환경 채점이 실패하면 성공으로 세지 않습니다.</td></tr>
<tr><td>실행 메타데이터</td><td>모델·설정·요청·시간·토큰·종료 이유</td><td>문항 ID로 연결해 모델 결과와 분리 보관합니다. API 키는 제외합니다.</td></tr></table></div>
<h2>언어별 묶음</h2><table><tr><th>언어</th><th>선택 문항</th><th>시도</th><th>성공</th></tr>{groups}</table>
<p>난이도 OCS/LCS 중 하나 이상 주석이 있는 문항: {difficulty_known} / {summary['selected']}개. 미주석은 난이도 0으로 처리하지 않습니다.</p></section>
<section><h2>통제변수와 사용량 측정</h2><p>통제변수 지문: <code>{esc(summary.get('control_fingerprint', '기록 없음 · 자동 이어 실행 불가'))}</code></p><p>프롬프트·대화 이력·도구·제작 환경·채점·API 생성 설정·요청 간격·예산은 사용량 감소를 위해 변경하지 않습니다. 성공 문항의 중복 호출을 방지하고 실제 제공된 사용량만 측정합니다. 토큰 감소를 보장하지 않습니다.</p><details><summary>기록된 통제변수</summary><pre>{esc(json.dumps(summary.get('controls', {}),ensure_ascii=False,indent=2))}</pre></details><h2>해석과 한계</h2><p class="note">이번 자료는 {esc(summary.get('data_source', 'english100/benchmark_cases.jsonl'))}에서 선택한 {summary['selected']}개 문항의 결과입니다. 한 모델의 단일 실행이며, 다른 모델과는 통제변수 지문이 같은 실행끼리만 비교합니다.</p>
<p>완료 선언 후 기존 채점기로 실제 피자와 제출을 검사합니다. 조건 미충족 {summary['grading_failed']}개, API 오류 {summary['api_errors']}개입니다. HTTP 429 발생 시 배치를 중단하고 남은 문항을 미실행으로 보존합니다. 토큰 합계는 서버가 제공한 전체 값이며 입력·출력 외 사고 토큰 등이 포함될 수 있습니다. 사용량을 받지 못한 요청은 토큰 집계에서 빠질 수 있으므로 청구 금액으로 간주하지 않습니다.</p>
<p>각 문항은 최대 요청 {summary['limits'].get('requests', '—')}회, 도구 {summary['limits'].get('tools', '—')}회, {summary['limits'].get('seconds', '—')}초 제한입니다. 자동 통신 재시도는 없습니다.</p>
<details><summary>실제 모델·SDK 설정</summary><pre>{esc(json.dumps(summary['model_settings'], ensure_ascii=False, indent=2))}</pre></details></section></main></html>'''
