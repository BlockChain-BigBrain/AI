"""Build a local A/B listening workbench; never invent expert listening labels."""
import csv
import hashlib
import json
from pathlib import Path
import evaluate_retrieval_baseline as baseline

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'layer2/artifacts'
OUT = ROOT / 'review_workbench'


def main():
    OUT.mkdir(exist_ok=True)
    originals = {baseline.track_id_from_original(p): p for p in baseline.audio_files(ROOT / 'original_music')}
    rows = [json.loads(line) for line in (ART / 'tonal_confirmation_checkpoint.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    policy = json.loads((ART / 'tonal_confirmation_evaluation.json').read_text(encoding='utf-8'))
    warn = policy['warn_threshold']
    normal = sorted([r for r in rows if r['dataset'] == 'safe_music'], key=lambda r: -r['score'])[:25]
    misses = [r for r in rows if r['dataset'] == 'positive' and (r['expected_score'] is None or r['expected_score'] < warn)]
    misses = sorted(misses, key=lambda r: (r['split'] != 'test', r['expected_score'] or -1))[:25]
    items = []
    def add(category, query, reference, evidence, metadata):
        query, reference = Path(query), Path(reference)
        assert query.is_file() and reference.is_file()
        digest = hashlib.sha256((str(query)+str(reference)).encode()).hexdigest()[:16]
        items.append({'id': digest, 'category': category, 'queryName': query.name, 'referenceName': reference.name,
                      'queryUrl': query.as_uri(), 'referenceUrl': reference.as_uri(),
                      'evidence': evidence, 'metadata': metadata, 'reviewStatus': 'pending_human_listening'})
    fresh_path = ART / 'fresh_audit_results.json'
    if fresh_path.exists():
        for row in json.loads(fresh_path.read_text(encoding='utf-8')):
            result = row['result']
            missed = row['label'] == 'synthetic_positive' and not result['expected_source_warn']
            warned = row['label'] == 'unverified_normal_candidate' and result['decision'] != 'PASS'
            if not (missed or warned) or not result['similarTracks']: continue
            match = result['similarTracks'][0]
            evidence = {**match['matchedSegments'][0], 'tonalScore': match['score']}
            add('추가 점검 · 정상 후보 경고' if warned else '추가 점검 · 놓친 양성 원곡',
                row['file'], originals[match['trackId']], evidence,
                {'expectedSource': row['expected_track_id'], 'kind': row['kind'], 'not_used_for_policy_fitting': True})
    for row in normal + misses:
        match = row['candidates'][0]
        add('정상 대조 후보 · 높은 유사도' if row['dataset'] == 'safe_music' else '합성 양성 · 놓친 원곡',
            row['file'], originals[match['trackId']], match,
            {'split': row['split'], 'transformation': row['query_kind'], 'expectedSource': row['expected_track_id'],
             'note': '자동 계산 근거입니다. 청취로 확정하지 않은 라벨은 학습·임계값 보정에 사용하지 않습니다.'})
    covers = json.loads((ART / 'tonal_cover_results.json').read_text(encoding='utf-8'))
    for row in sorted(covers, key=lambda r: -r['tonal_rank'])[:10]:
        work = row['work_id']; candidate = row['matches'][0]
        clips = ROOT / 'layer2/external_data/covers80/pilot_clips'
        add('독립 연주 · 잘못 검색된 후보', clips / f'{work}__query.wav', clips / f'{candidate["work_id"]}__reference.wav',
            candidate, {'expectedSource': work, 'tonalRank': row['tonal_rank'], 'clapRank': row['clap_rank']})
    payload = json.dumps(items, ensure_ascii=False).replace('</', '<\\/')
    html = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Track AI 청취 검수</title><style>body{font:16px system-ui;background:#10151e;color:#eef2fa;max-width:1000px;margin:24px auto;padding:16px}button,input,select,textarea{font:inherit;padding:10px;background:#202b40;color:white;border:1px solid #5b6c88;border-radius:6px}button{cursor:pointer}audio{width:100%}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}.card{padding:20px;background:#182234;border-radius:12px;margin:20px 0}p,pre{overflow-wrap:anywhere;white-space:pre-wrap}textarea{width:90%}@media(max-width:650px){.pair{grid-template-columns:1fr}}label{display:block;margin:12px 0}</style>
<h1>청취 검수 · 완료 여부 직접 기록</h1><p>자동 비교 결과와 사람의 청취 판단을 구분합니다. 동일 작품·다른 작품·판단 유보는 법적 표절 판정이 아닙니다. 저장은 이 브라우저에만 적용되며 JSON 내보내기로 검토본을 보관하세요.</p>
<label>검수자 <input id="reviewer" placeholder="이름 또는 검수자 ID"></label>
<button id="prev">이전</button> <span id="count"></span> <button id="next">다음</button> <button id="export">검수본 JSON 내보내기</button>
<div class="card"><h2 id="category"></h2><div class="pair"><div><h3>업로드 / 질의</h3><p id="qn"></p><audio id="q" controls></audio><button id="qs">매칭 시작점</button></div><div><h3>검색 후보</h3><p id="rn"></p><audio id="r" controls></audio><button id="rs">매칭 시작점</button></div></div>
<details><summary>자동 계산 근거 · 정답 정보</summary><pre id="evidence"></pre></details>
<label>청취 판단 <select id="label"><option value="pending">미검수</option><option value="same_work">동일 작품 관계</option><option value="different_work">다른 작품으로 판단</option><option value="uncertain">판단 유보</option></select></label>
<label>근거·확인 구간 <textarea id="notes" rows="4"></textarea></label><button id="save">현재 검수 저장</button><p id="message" aria-live="polite"></p></div>
<script>const items=PAYLOAD;const $=id=>document.getElementById(id);const key='track-ai-review-v1';let saved={};try{saved=JSON.parse(localStorage.getItem(key)||'{}')}catch{}let index=0;
function render(){const x=items[index],s=saved[x.id]||{};$('count').textContent=`${index+1} / ${items.length}`;$('category').textContent=x.category;$('qn').textContent=x.queryName;$('rn').textContent=x.referenceName;$('q').src=x.queryUrl;$('r').src=x.referenceUrl;$('evidence').textContent=JSON.stringify({score:x.evidence,context:x.metadata},null,2);$('label').value=s.label||'pending';$('notes').value=s.notes||'';$('reviewer').value=s.reviewer||$('reviewer').value;$('message').textContent=s.label&&s.label!=='pending'?'청취 검수 기록 있음':'아직 사람이 청취·판단하지 않은 항목입니다.'}
$('save').onclick=()=>{if($('label').value!=='pending'&&(!$('reviewer').value.trim()||!$('notes').value.trim())){$('message').textContent='검수자와 판단 근거를 입력해 주세요.';return}saved[items[index].id]={label:$('label').value,notes:$('notes').value,reviewer:$('reviewer').value,reviewedAt:new Date().toISOString()};localStorage.setItem(key,JSON.stringify(saved));$('message').textContent='이 브라우저에 저장했습니다.'};$('prev').onclick=()=>{index=(index-1+items.length)%items.length;render()};$('next').onclick=()=>{index=(index+1)%items.length;render()};$('qs').onclick=()=>{$('q').currentTime=items[index].evidence.queryStartSec||0};$('rs').onclick=()=>{$('r').currentTime=items[index].evidence.refStartSec||0};$('export').onclick=()=>{const data={version:1,exportedAt:new Date().toISOString(),notLegalVerdicts:true,items:items.map(x=>({...x,humanReview:saved[x.id]||{label:'pending'}}))};const u=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='track-ai-listening-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};render();</script></html>'''
    (OUT / 'index.html').write_text(html.replace('PAYLOAD', payload), encoding='utf-8')
    (ART / 'listening_review_preparation.json').write_text(json.dumps({'status': 'prepared', 'cases': len(items),
        'audio_paths_checked': True, 'human_listening_complete': False,
        'page': 'review_workbench/index.html', 'automatic_label_import': False}, indent=2), encoding='utf-8')
    print(f'Prepared {len(items)} A/B cases; human listening remains pending.')


if __name__ == '__main__': main()
