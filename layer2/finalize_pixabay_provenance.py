"""Join metadata inventory with per-track public-page observations."""
from collections import Counter
import csv
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'layer2/artifacts/pixabay_provenance'


def main():
    inventory=json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))
    web=json.loads((OUT/'web_evidence.json').read_text(encoding='utf-8'))
    evidence={r['media_id']:r for r in web['evidence']}
    rows=[]
    for original in inventory:
        proof=evidence.get(original['media_id_candidate'],{})
        row={k:original[k] for k in ('folder','file','track_id','sha256','media_id_candidate')}
        row.update(status=proof.get('status','no_matched_page'), source_url=proof.get('url',''),
                   page_ai_label=proof.get('label',''),checked_utc=proof.get('checked_utc',''),
                   source_link_method='filename_media_id_to_official_page' if proof else 'unresolved',
                   metadata_ai_tool_terms=';'.join(original['ai_tool_metadata_terms']),
                   user_reported_source='Pixabay',pure_ai_creation_verified=False)
        rows.append(row)
    with (OUT/'file_audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    grouped={folder:dict(Counter(r['status'] for r in rows if r['folder']==folder)) for folder in ('original_music','music','premusic')}
    allow={folder:[r for r in rows if r['folder']==folder and r['status']=='pixabay_ai_label_observed'] for folder in grouped}
    (OUT/'ai_label_allowlist.json').write_text(json.dumps(allow,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'files':len(rows),'folders':grouped,'unique_media_ids_searched':web['searched'],
             'unique_music_pages_attempted':len(evidence),
             'unique_music_pages_observed':sum(r['status']!='page_fetch_unavailable' for r in evidence.values()),'pure_ai_creation_verified':0,
             'ai_label_means':'Platform-labelled AI involvement, including generated or modified; not verified pure generation.',
             'missing_label_means':'Unknown, never classified as human-made.',
             'evidence_binding':'Local SHA256 and filename media ID; no server-side download hash available.',
             'official_guideline':'https://pixabay.com/blog/posts/audio-quality-guidelines-182/'}
    (OUT/'audit_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    names={'original_music':'원본 검색곡','music':'정상후보','premusic':'예비 음원'}
    lines=['# Pixabay AI 표시 확인 결과','',
           '**무료 이용과 AI 생성 여부는 별개입니다. 이번 결과는 곡별 공식 페이지의 AI 표시 관찰이며, 순수 AI 생성 공정의 증명은 아닙니다.**','',
           '| 폴더 | AI 표시 관찰 | 페이지에서 AI 표시 미관찰 | 페이지 미확인·접근 불가 | 합계 |','|---|---:|---:|---:|---:|']
    for folder,count in grouped.items():
        lines.append(f"| {names[folder]} | {count.get('pixabay_ai_label_observed',0)} | {count.get('page_no_ai_label_observed',0)} | {count.get('no_matched_page',0)+count.get('page_fetch_unavailable',0)} | {sum(count.values())} |")
    lines+=['', '## 확인 방법과 한계','',
            '1,500개 로컬 파일의 메타데이터를 검사했습니다. 명시적 AI 생성 도구 표기와 Pixabay URL은 발견하지 못했습니다. 파일명에서 추출한 1,227개 고유 미디어 ID를 제목·작성자 및 ID 검색으로 조사하고, 발견된 곡별 공식 페이지를 열어 표시를 확인했습니다. 미확인 곡을 AI 또는 사람 제작으로 추정하지 않았습니다.',
            '곡별 결과·원본 파일 SHA-256·공식 페이지 URL은 `layer2/artifacts/pixabay_provenance/file_audit.csv`에 기록했습니다. 페이지와 로컬 파일의 대응은 파일명 ID 기준이며 서버 음원 해시 대조까지 완료한 것은 아닙니다.',
            'Pixabay는 AI 표시에 생성뿐 아니라 AI 수정도 포함하며 표시 오류가 가능하다고 안내합니다. 표시가 없어도 비AI라는 의미가 아닙니다. 따라서 “AI 표시 관찰군”과 “순수 AI 생성 확인군”을 구분합니다. 후자는 현재 확인된 근거가 없습니다.',
            '참고: [Pixabay 공식 AI 오디오 표시 안내](https://pixabay.com/blog/posts/audio-quality-guidelines-182/).','',
            '원본 파일을 삭제·이동하지 않았습니다. 기존 1,000곡·정상 300곡 평가는 혼합·미확인 DB 결과로 보존하고, AI 표시 관찰군의 별도 평가 결과와 구분합니다.']
    (ROOT/'PIXABAY_AI_AUDIT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
