"""Publish the finished premusic holdout diagnostic with work-level evidence."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "layer2" / "artifacts"
DATA = ROOT / ".runtime-tests" / "premusic-holdout-20261029"


def rate(value):
    return f"{value * 100:.2f}%" if value is not None else "—"


def main():
    frozen = json.loads((DATA / "frozen_selection.json").read_text(encoding="utf-8"))
    summary = json.loads((DATA / "summary.json").read_text(encoding="utf-8"))
    if summary["status"] != "completed" or summary["queries_recorded"] != 200 or summary["queries_failed"]:
        raise RuntimeError("The 50-work, 200-query evaluation has not completed successfully")
    results = [json.loads(line) for line in (DATA / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    by_work = defaultdict(dict)
    for result in results:
        by_work[result["work_id"]][result["kind"]] = result
    analysis = []
    for work in frozen["selected"]:
        records = by_work[work["sha256"]]
        def candidate(kind):
            result = records[kind]["result"]
            match = result.get("similarTracks", [])
            first = match[0] if match else {}
            return result["decision"], result.get("similarityScore"), first.get("trackId", "")
        full = candidate("full")
        start, middle, end = (candidate(kind) for kind in ("start30", "middle30", "end30"))
        all_crops = (start, middle, end)
        analysis.append({"work": work["name"], "sha256": work["sha256"],
            "source_status": work["source_status"], "source_url": work["source_url"],
            "full_decision": full[0], "full_score": full[1], "full_top_match": full[2],
            "start_decision": start[0], "start_score": start[1], "start_top_match": start[2],
            "middle_decision": middle[0], "middle_score": middle[1], "middle_top_match": middle[2],
            "end_decision": end[0], "end_score": end[1], "end_top_match": end[2],
            "crop_work_warn": any(x[0] in ("WARN", "HOLD", "BLOCK") for x in all_crops),
            "crop_work_hold_or_block": any(x[0] in ("HOLD", "BLOCK") for x in all_crops)})
    evidence = ART / "premusic_holdout_50_work_results_20261029.csv"
    with evidence.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(analysis[0]))
        writer.writeheader()
        writer.writerows(analysis)
    source_counts = Counter(r["source_status"] for r in frozen["selected"])
    filename_prefix_counts = Counter(r["name"].split("-", 1)[0] for r in frozen["selected"])
    full = summary["full"]
    crops = summary["three_30s_work_union"]
    lines = [
        "# premusic 50작품 분리 진단 — 2026-10-29", "",
        "## 이번에 실제로 한 일", "",
        "원곡 1,000곡·기존 정상후보 300곡·premusic 200곡의 파일 SHA-256을 현재 파일로 재확인했습니다. "
        "기존 평가 manifest와 비교해 이미 등장한 premusic 원본을 제외하고, Pixabay 미디어 ID·동일 파일 해시·원곡 지문 근접 일치·"
        "music 및 premusic 내부 지문 근접 일치를 확인했습니다. 200곡 중 90곡이 이 선별을 통과했습니다. "
        "모델 점수를 보기 전 SHA-256 기반 고정 규칙으로 50곡을 선택하고 임계값을 동결했습니다.", "",
        "기존 manifest 등장이라는 격리 사유에는 **실제로 평가된 곡과 평가 전 제외 목록에 있던 곡이 모두 포함**됩니다. "
        "사유별 개수는 서로 겹치므로 합산해 제외곡 수로 해석하면 안 됩니다. 지문 검색은 근접 녹음을 걸러내는 제한된 검사이며, "
        "일치가 없다고 곡의 권리·작품 독립성이 증명되는 것은 아닙니다.", "",
        "## 현재 정책으로 평가한 결과", "",
        f"현재 AI 표시군 검색 기준 원곡은 34곡이고, WARN 임계값은 0.3474893216, HOLD는 0.8337449399입니다. "
        f"완곡 50개와 각 작품의 시작·중간·끝 30초 조각 150개, 총 200개를 평가했습니다. "
        f"조각 셋 중 하나라도 경고면 작품 전체를 경고로 집계합니다. 실패 쿼리는 {summary['queries_failed']}개입니다.", "",
        "| 평가 단위 | 경고 작품 | 관측 경고율 | 단측 95% 상한 | HOLD·BLOCK 작품 | 관측 HOLD·BLOCK율 | 단측 95% 상한 |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| 완곡 50작품 | {full['warning_works']}/50 | {rate(full['warn_rate'])} | {rate(full['warn_one_sided_95_upper'])} | {full['hold_or_block_works']}/50 | {rate(full['hold_rate'])} | {rate(full['hold_one_sided_95_upper'])} |",
        f"| 30초 조각 3개를 묶은 50작품 | {crops['warning_works']}/50 | {rate(crops['warn_rate'])} | {rate(crops['warn_one_sided_95_upper'])} | {crops['hold_or_block_works']}/50 | {rate(crops['hold_rate'])} | {rate(crops['hold_one_sided_95_upper'])} |",
        "",
        f"현재 개발 목표는 정상 WARN 이하 10%, HOLD 이하 2%입니다. 관측치 기준 완곡 경고 목표는 "
        f"{'충족' if full['warn_point_target_met'] else '미달'}이며, 30초 작품 경고 목표는 "
        f"{'충족' if crops['warn_point_target_met'] else '미달'}입니다. 신뢰상한을 기준으로 두 목표를 충족했다고 할 수 있는지는 "
        f"완곡 WARN {'예' if full['warn_upper_bound_target_met'] else '아니오'}, "
        f"30초 WARN {'예' if crops['warn_upper_bound_target_met'] else '아니오'}, "
        f"완곡 HOLD {'예' if full['hold_upper_bound_target_met'] else '아니오'}, "
        f"30초 HOLD {'예' if crops['hold_upper_bound_target_met'] else '아니오'}입니다.", "",
        "## 경고가 발생한 위치와 사례", "",
        f"30초 조각별 경고는 시작 {sum(r['start_decision'] in ('WARN','HOLD','BLOCK') for r in analysis)}개, "
        f"중간 {sum(r['middle_decision'] in ('WARN','HOLD','BLOCK') for r in analysis)}개, "
        f"끝 {sum(r['end_decision'] in ('WARN','HOLD','BLOCK') for r in analysis)}개입니다. "
        "같은 작품이 여러 위치에서 경고될 수 있으므로 세 숫자를 더해 작품 수로 쓰지 않습니다.", "",
        "최상위 매칭은 `the_mountain` 계열 등 몇몇 기준곡에 반복되는 경향이 있습니다. "
        "이 정보만으로 실제 녹음 재사용과 유사한 편곡을 가를 수 없으므로 개별 경고를 확정 오탐이라고 부르지 않습니다.", "",
        "| 정상후보 작품 | 가장 높은 30초 경고 점수 | 최상위 매칭 기준곡 |", "|---|---:|---|",
    ]
    warn_examples=[]
    for row in analysis:
        warnings=[(row[f'{kind}_score'],row[f'{kind}_top_match'])
                  for kind in ('start','middle','end') if row[f'{kind}_decision'] in ('WARN','HOLD','BLOCK')]
        if warnings:
            score,match=max(warnings,key=lambda item:float(item[0] or 0))
            warn_examples.append((float(score),row['work'],match))
    for score,work,match in sorted(warn_examples,reverse=True)[:5]:
        lines.append(f"| `{work}` | {score:.3f} | `{match}` |")
    lines += ["",
        "## 해석 범위", "",
        f"2026-10-23에 저장된 출처 감사 기준, 선택된 50곡의 Pixabay 페이지 상태는 AI 표시 없음 {source_counts.get('page_no_ai_label_observed',0)}곡, "
        f"확인 가능한 일치 페이지 없음 {source_counts.get('no_matched_page',0)}곡입니다. "
        "50곡 모두 순수 AI 생성 근거가 확인되지 않았습니다. 따라서 이번 수치는 **미사용 premusic 정상후보의 추가 진단**이며 "
        "멘토가 요청한 ‘독립 생성 AI 음원 30~50곡’ 검증 결과로 제시할 수 없습니다. "
        "기존 자료에 노출된 곡을 제외했더라도 Pixabay 후보군이 목표 AI 생성 음원 모집단을 대표한다는 근거도 없습니다.", "",
        "파일명 접두어 기준 구성은 " + ", ".join(f"{name} {count}곡" for name, count in filename_prefix_counts.most_common()) +
        "입니다. 같은 접두어의 곡들은 제작 방식이 비슷할 수 있으므로 50곡을 서로 독립인 시장 표본으로 간주하기 어렵습니다.", "",
        "단측 95% 상한은 작품이 서로 독립이고 대표성 있게 추출됐다는 가정의 이항 계산입니다. "
        "샘플이 데이터베이스·출처·장르별로 편중되면 상한을 실제 운영 오탐률 보증으로 해석할 수 없습니다. "
        "30초 결과는 세 위치를 샘플링한 것이며 모든 30초 구간을 검사한 결과가 아닙니다. "
        "정상 후보만 평가했으므로 변형 양성의 원곡 재현율은 여기서 계산되지 않습니다.", "",
        "## 근거 파일", "",
        "- 선별·고정: `.runtime-tests/premusic-holdout-20261029/frozen_selection.json`",
        "- 200곡 선별 감사: `.runtime-tests/premusic-holdout-20261029/screen_all_200.json`",
        "- 200개 실제 쿼리 결과: `.runtime-tests/premusic-holdout-20261029/results.jsonl`",
        "- 요약: `.runtime-tests/premusic-holdout-20261029/summary.json`",
        "- 작품별 전체 판정·점수·최상위 매칭: `layer2/artifacts/premusic_holdout_50_work_results_20261029.csv`", "",
        "이번 200곡 선별은 정리 전 음원 200곡을 기준으로 고정했습니다. 이후 premusic 파일을 정리했으므로 "
        "선별 단계는 당시의 동결 감사 파일로 확인하세요. `python layer2/evaluate_premusic_holdout.py`는 사용곡의 이동 대응표를 이용해 "
        "기존 평가 결과를 다시 확인할 수 있습니다. 임계값은 다시 맞추지 않습니다.", "",
    ]
    reorganization=ART/'premusic_reorganization_20261029.json'
    if reorganization.exists():
        moved=json.loads(reorganization.read_text(encoding='utf-8'))
        lines += ["## 평가 후 premusic 파일 정리", "",
            f"사용곡 {moved['moved']}개를 `premusic_used/`의 평가별 폴더로 옮기고, "
            f"SHA-256이 동일한 보존본이 있는 중복 파일 {moved['exact_duplicates_deleted']}개를 premusic에서 제거했습니다. "
            f"현재 premusic에는 {moved['premusic_remaining']}개가 남습니다. "
            "과거 manifest는 당시 경로 그대로 보존하고 `premusic_used/usage_manifest.csv`에서 새 경로와 사용처를 확인합니다.", "",
            "이 정리는 평가가 모두 끝난 뒤 수행됐습니다. 이미 고정한 50곡과 임계값, 200개 결과를 바꾸지 않았습니다.", ""]
    (ROOT / "PREMUSIC_HOLDOUT_20261029.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"full_warn": full["warning_works"], "crop_warn": crops["warning_works"],
        "full_hold": full["hold_or_block_works"], "crop_hold": crops["hold_or_block_works"],
        "source_status_counts": dict(source_counts)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
