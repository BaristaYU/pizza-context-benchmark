"""Run identities, conservative resume validation and immutable attempt history."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re


def dataset_fingerprint(cases):
    return hashlib.sha256(json.dumps(cases,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def write_json(path,value):
    path=Path(path)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)


def prepare_run(folder,cases,provider,model,resume=False,controls=None):
    folder=Path(folder)
    ids=[case['id'] for case in cases]
    if not cases or len(set(ids))!=len(ids) or any(not isinstance(i,str) or not re.fullmatch('[A-Za-z0-9_-]+',i) for i in ids):
        raise ValueError('문항 ID가 없거나 중복되거나 안전한 파일 이름이 아닙니다.')
    manifest={'version':1,'provider':provider,'model':model,'case_ids':ids,
              'dataset_fingerprint':dataset_fingerprint(cases),'created_at':datetime.now().astimezone().isoformat()}
    if controls is not None:
        manifest['controls']=controls
        manifest['control_fingerprint']=controls['fingerprint']
        # Service settings may differ between compared runs, but a resumed run must keep them.
        if controls.get('service_fingerprint'):manifest['service_fingerprint']=controls['service_fingerprint']
    if not resume:
        folder.mkdir(parents=True,exist_ok=False)
    elif not folder.is_dir(): raise ValueError('이어 실행할 결과 폴더가 없습니다.')
    reports=[]
    for case in cases:
        path=folder/(case['id']+'.json')
        reports.append(json.loads(path.read_text(encoding='utf-8')) if resume and path.exists() else
                       {'case_id':case['id'],'model':model,'provider':provider,'termination':'not_run','requests':0})
    if resume:
        path=folder/'run_manifest.json'
        if path.exists():
            old=json.loads(path.read_text(encoding='utf-8'))
            if controls is not None and old.get('control_fingerprint')!=controls['fingerprint']:
                raise ValueError('통제변수 기록이 없거나 현재 설정과 다릅니다. 이전 결과는 보존하며 새 실험 폴더에서 실행하세요.')
            if controls is not None and old.get('service_fingerprint')!=controls.get('service_fingerprint'):
                raise ValueError('서비스 생성 설정이 이전 실행과 다릅니다. 이전 결과는 보존하며 새 실험 폴더에서 실행하세요.')
            for name in ('provider','model','case_ids','dataset_fingerprint'):
                if old.get(name)!=manifest[name]: raise ValueError('이전 실행과 서비스·모델·문항 데이터가 다릅니다. 새 결과 폴더를 사용하세요.')
            manifest=old
        else:
            if controls is not None:
                raise ValueError('이전 결과에는 통제변수 지문이 없습니다. 조건 동등성을 증명할 수 없어 자동 이어 실행하지 않습니다.')
            # Legacy runs lacked a full data hash. Verify every available observation before adoption.
            summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
            old_provider=summary.get('provider') or str(summary.get('model_settings',{}).get('provider','gemini')).lower()
            if summary.get('model')!=model or old_provider!=provider or [r['case_id'] for r in summary['rows']]!=ids:
                raise ValueError('이전 결과의 서비스·모델·문항 ID가 다릅니다.')
            by_id={r['case_id']:r for r in summary['rows']}
            for case,report in zip(cases,reports):
                row=by_id[case['id']]
                if row.get('order_text')!=case['question'].get('order_text') or row.get('language')!=case['question'].get('language'):
                    raise ValueError('이전 문항의 주문·언어가 다릅니다.')
                if 'state' in report and report['state']!=case['state']: raise ValueError('이전 초기 상태가 다릅니다.')
            manifest['legacy_import_note']='Original run had no dataset hash. IDs, question text/language and recorded initial states matched. Original reference A hash cannot be proven retroactively; current complete data hash is enforced from this import onward.'
        for report,case in zip(reports,cases):
            if report.get('case_id')!=case['id'] or report.get('model')!=model:
                raise ValueError('문항 실행 결과의 ID 또는 모델이 다릅니다.')
    write_json(folder/'run_manifest.json',manifest)
    for report in reports:
        path=folder/(report['case_id']+'.json')
        if not path.exists(): write_json(path,report)
    return manifest,reports


def store_attempt(folder,new,previous):
    folder=Path(folder)
    history=deepcopy(previous.get('attempts',[]))
    if not history and previous.get('termination')!='not_run':
        history=[{k:deepcopy(v) for k,v in previous.items() if k!='attempts'}]
    for index,attempt in enumerate(history,1):
        path=folder/'history'/new['case_id']/f'attempt_{index:04d}.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists(): write_json(path,attempt)
    snapshot={k:deepcopy(v) for k,v in new.items() if k!='attempts'}
    new_history_path=None
    if new['termination']!='not_run':
        history.append(snapshot)
        new_history_path=folder/'history'/new['case_id']/f'attempt_{len(history):04d}.json'
        new_history_path.parent.mkdir(parents=True,exist_ok=True)
        if new_history_path.exists():raise ValueError('실행 이력 파일이 이미 존재합니다. 덮어쓰지 않습니다.')
    value={**snapshot,'attempts':history}
    # The atomic latest record is authoritative: a crash cannot leave a completed case uncommitted.
    write_json(folder/(new['case_id']+'.json'),value)
    if new_history_path is not None:write_json(new_history_path,snapshot)
    return value
