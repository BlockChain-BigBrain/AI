"""Replace exactly 17 reported duplicate controls after fresh fingerprint checks."""
import csv
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from import_pixabay_batch import audio_files, balanced_audio_files, contains_sequence, Fingerprint, sha256_file, FPCALC

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'layer2/artifacts'

def fingerprint_file(path):
    data = subprocess.run([str(FPCALC), '-raw', '-json', str(path)], capture_output=True, text=True, encoding='utf-8', check=True, timeout=240)
    value = json.loads(data.stdout)
    frames = value['fingerprint']
    assert frames, f'Empty fingerprint: {path}'
    return Fingerprint(path, sha256_file(path), float(value['duration']), [int(f) & 0xffffffff for f in frames])

def match(a, refs):
    for b in refs:
        if a.sha256 == b.sha256:
            return b
        short, long = sorted((a, b), key=lambda x: len(x.frames))
        if contains_sequence(short.frames, long.frames):
            return b
    return None

def main():
    report = ART / 'music_duplicate_report.csv'
    rows = list(csv.DictReader(report.open(encoding='utf-8-sig')))
    duplicates = [Path(r['music_file']) for r in rows if r['status'] == 'DUPLICATE_PREVIEW']
    assert len(duplicates) == 17, 'Expected exactly 17 duplicate candidates'
    music = audio_files(ROOT / 'music')
    assert len(music) == 300
    for p in duplicates:
        assert p.resolve().parent == (ROOT / 'music').resolve() and p.is_file()
    files = audio_files(ROOT / 'original_music') + music
    with ThreadPoolExecutor(max_workers=6) as pool:
        fps = dict(zip(files, pool.map(fingerprint_file, files)))
    originals = [fps[p] for p in audio_files(ROOT / 'original_music')]
    assert all(match(fps[p], originals) for p in duplicates)
    kept = [fps[p] for p in music if p not in duplicates]
    assert all(match(a, originals) is None for a in kept)
    selected = []
    for p in balanced_audio_files(ROOT / 'premusic'):
        candidate = fingerprint_file(p)
        if candidate.duration < 10:
            continue
        if match(candidate, originals + kept + selected) is None:
            assert not (ROOT / 'music' / p.name).exists()
            selected.append(candidate)
            print(f'[selected {len(selected)}/17] {p.name}', flush=True)
        if len(selected) == 17:
            break
    assert len(selected) == 17, 'Not enough verified replacements; no files changed'
    final = kept + selected
    for i, fp in enumerate(final):
        assert match(fp, originals + final[:i]) is None, f'Duplicate planned control: {fp.path}'
    # Backup exact removed bytes and old evidence before any mutation.
    backup = ART / 'control_replacement_20261022'
    backup.mkdir(exist_ok=False)
    shutil.copy2(report, backup / report.name)
    for p in duplicates:
        shutil.copy2(p, backup / p.name)
    changes = []
    for p in duplicates:
        p.unlink()
        changes.append({'action': 'removed_duplicate', 'file': str(p), 'sha256': fps[p].sha256})
    for fp in selected:
        target = ROOT / 'music' / fp.path.name
        old = fp.path
        shutil.move(str(old), str(target))
        fp.path = target
        changes.append({'action': 'moved_from_premusic', 'file': str(target), 'previous_path': str(old), 'sha256': fp.sha256})
    final = kept + selected
    assert len(audio_files(ROOT / 'music')) == 300
    for i, fp in enumerate(final):
        assert match(fp, originals + final[:i]) is None, f'Duplicate remaining: {fp.path}'
    with report.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['music_file','matched_original_file','status','details'])
        w.writeheader()
        w.writerows({'music_file': str(fp.path), 'matched_original_file': '', 'status': 'NO_EXACT_MATCH', 'details': 'Fresh SHA-256 and Chromaprint sequence check against original_music and all music controls; fpcalc default analysis window'} for fp in final)
    (backup / 'changes.json').write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Verified 300 controls; removed 17; moved 17; originals unchanged.', flush=True)

if __name__ == '__main__':
    main()
