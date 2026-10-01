"""LEGACY: build CLAP embeddings and train a weakly supervised metric head.

This experiment is not used by the current retrieval/risk-score pipeline. It
groups windows by source-track identity; that objective is not plagiarism
classification. Do not use its checkpoint as the current Layer 2 model.

The pretrained CLAP audio encoder stays frozen. We train only a projection
head using track identity as a weak label: segments from one source track are
positive examples; segments from different tracks are negatives.

Run with the Anaconda Python environment that has torch installed:
    python layer2/legacy/train_layer2.py
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import defaultdict
from pathlib import Path

import librosa
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import ClapAudioModelWithProjection, ClapProcessor


PROJECT_DIR = Path(__file__).resolve().parents[2]
SEGMENTS_DIR = PROJECT_DIR / "segments"
ARTIFACT_DIR = PROJECT_DIR / "layer2" / "artifacts"
BASE_MODEL = "laion/clap-htsat-unfused"
SAMPLE_RATE = 48_000
EMBEDDING_DIM = 512
SEGMENT_SUFFIX = re.compile(r"_seg(?:ment)?_?\d+$", re.IGNORECASE)


class MetricHead(nn.Module):
    def __init__(self, input_dim: int = EMBEDDING_DIM, output_dim: int = EMBEDDING_DIM):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_dim, 256),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(256, output_dim),
        )

    def forward(self, embeddings: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.layers(embeddings), p=2, dim=-1)


def source_track_id(path: Path) -> str:
    relative_parent = path.parent.relative_to(SEGMENTS_DIR)
    if relative_parent == Path("segments") or relative_parent == Path("."):
        # Older cutter output put multiple songs in one folder and encoded the
        # chunk number in names such as song-name_seg001.wav.
        return SEGMENT_SUFFIX.sub("", path.stem)
    return str(relative_parent).replace("\\", "/")


def collect_segments() -> tuple[list[Path], list[str]]:
    paths = sorted(path for path in SEGMENTS_DIR.rglob("*.wav") if path.is_file())
    track_ids = [source_track_id(path) for path in paths]
    return paths, track_ids


def extract_embeddings(
    paths: list[Path], batch_size: int, device: torch.device
) -> np.ndarray:
    print(f"CLAP 가중치 준비: {BASE_MODEL}")
    model = ClapAudioModelWithProjection.from_pretrained(BASE_MODEL).to(device)
    processor = ClapProcessor.from_pretrained(BASE_MODEL)
    model.eval()

    results: list[np.ndarray] = []
    for start in range(0, len(paths), batch_size):
        batch_paths = paths[start : start + batch_size]
        audio_batch = [
            librosa.load(str(path), sr=SAMPLE_RATE, mono=True)[0]
            for path in batch_paths
        ]
        inputs = processor(
            audio=audio_batch,
            sampling_rate=SAMPLE_RATE,
            return_tensors="pt",
            padding=True,
        ).to(device)
        with torch.inference_mode():
            output = model(**inputs)
        results.append(F.normalize(output.audio_embeds, dim=-1).cpu().numpy())
        done = min(start + len(batch_paths), len(paths))
        print(f"임베딩 추출: {done}/{len(paths)}")

    del model
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return np.concatenate(results, axis=0).astype(np.float32)


def supervised_contrastive_loss(
    vectors: torch.Tensor, labels: torch.Tensor, temperature: float = 0.07
) -> torch.Tensor:
    vectors = F.normalize(vectors, dim=-1)
    logits = vectors @ vectors.T / temperature
    count = vectors.shape[0]
    not_self = ~torch.eye(count, dtype=torch.bool, device=vectors.device)
    positives = labels[:, None].eq(labels[None, :]) & not_self
    logits = logits.masked_fill(~not_self, -torch.inf)
    log_prob = logits - torch.logsumexp(logits, dim=1, keepdim=True)
    positive_count = positives.sum(dim=1)
    valid = positive_count > 0
    per_anchor = -torch.where(positives, log_prob, 0.0).sum(dim=1) / positive_count.clamp_min(1)
    return per_anchor[valid].mean()


def sample_balanced_batch(
    groups: dict[int, np.ndarray], track_labels: list[int],
    tracks_per_batch: int, samples_per_track: int,
) -> np.ndarray:
    chosen_tracks = random.sample(track_labels, min(tracks_per_batch, len(track_labels)))
    picks: list[int] = []
    for track in chosen_tracks:
        indices = groups[track]
        picks.extend(np.random.choice(indices, samples_per_track, replace=len(indices) < samples_per_track))
    return np.asarray(picks, dtype=np.int64)


def train_metric_head(
    embeddings: np.ndarray, track_ids: list[str], epochs: int, steps_per_epoch: int,
    device: torch.device,
) -> tuple[MetricHead, list[dict[str, float]]]:
    unique_tracks = sorted(set(track_ids))
    track_to_label = {track: index for index, track in enumerate(unique_tracks)}
    labels_np = np.asarray([track_to_label[track] for track in track_ids], dtype=np.int64)
    groups: dict[int, np.ndarray] = {
        label: np.flatnonzero(labels_np == label)
        for label in range(len(unique_tracks))
    }
    usable_labels = [label for label, indices in groups.items() if len(indices) >= 2]
    if len(usable_labels) < 2:
        raise RuntimeError("학습쌍을 만들 곡이 부족합니다. 곡별 폴더/파일명을 확인하세요.")

    x = torch.from_numpy(embeddings).to(device)
    y = torch.from_numpy(labels_np).to(device)
    head = MetricHead().to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-4)
    steps_per_epoch = steps_per_epoch or max(20, min(100, len(embeddings) // 128))
    history: list[dict[str, float]] = []

    for epoch in range(1, epochs + 1):
        head.train()
        losses: list[float] = []
        for _ in range(steps_per_epoch):
            indices_np = sample_balanced_batch(groups, usable_labels, 32, 4)
            indices = torch.from_numpy(indices_np).to(device)
            optimizer.zero_grad(set_to_none=True)
            projected = head(x[indices])
            loss = supervised_contrastive_loss(projected, y[indices])
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))

        epoch_loss = float(np.mean(losses))
        history.append({"epoch": float(epoch), "loss": epoch_loss})
        print(f"학습 epoch {epoch}/{epochs} | contrastive loss={epoch_loss:.4f}")

    return head, history


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--steps-per-epoch", type=int, default=0)
    parser.add_argument("--refresh-embeddings", action="store_true")
    parser.add_argument("--max-files", type=int, default=0, help="small smoke run; 0 uses all WAV segments")
    args = parser.parse_args()

    if not SEGMENTS_DIR.is_dir():
        raise SystemExit(f"segments 폴더가 없습니다: {SEGMENTS_DIR}")
    paths, track_ids = collect_segments()
    if args.max_files:
        paths, track_ids = paths[: args.max_files], track_ids[: args.max_files]
    if not paths:
        raise SystemExit(f"WAV 학습 데이터가 없습니다: {SEGMENTS_DIR}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    metadata_path = ARTIFACT_DIR / "segment_manifest.csv"
    with metadata_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["segment_path", "track_id"])
        writer.writerows((str(path), track) for path, track in zip(paths, track_ids))

    cache_path = ARTIFACT_DIR / "clap_embeddings.npz"
    paths_array = np.asarray([str(path) for path in paths])
    if cache_path.exists() and not args.refresh_embeddings:
        cached = np.load(cache_path, allow_pickle=False)
        if np.array_equal(cached["paths"], paths_array):
            embeddings = cached["embeddings"].astype(np.float32)
            print(f"기존 CLAP 임베딩 재사용: {len(embeddings)}개")
        else:
            embeddings = np.empty((0, EMBEDDING_DIM), dtype=np.float32)
    else:
        embeddings = np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"학습 데이터: {len(paths)}개 WAV, {len(set(track_ids))}개 추정 곡 ID | device={device}")
    if len(embeddings) == 0:
        embeddings = extract_embeddings(paths, args.batch_size, device)
        np.savez_compressed(cache_path, embeddings=embeddings, paths=paths_array)

    head, history = train_metric_head(
        embeddings, track_ids, args.epochs, args.steps_per_epoch, device
    )
    head.eval()
    with torch.inference_mode():
        projected = np.concatenate([
            head(torch.from_numpy(embeddings[start : start + 1024]).to(device)).cpu().numpy()
            for start in range(0, len(embeddings), 1024)
        ]).astype(np.float32)

    torch.save({
        "state_dict": head.cpu().state_dict(),
        "input_dim": EMBEDDING_DIM,
        "output_dim": EMBEDDING_DIM,
        "base_model": BASE_MODEL,
        "training_method": "weakly_supervised_same_track_contrastive",
        "track_count": len(set(track_ids)),
        "segment_count": len(paths),
        "epochs": args.epochs,
        "final_loss": history[-1]["loss"],
    }, ARTIFACT_DIR / "layer2_metric_head.pt")
    np.savez_compressed(
        ARTIFACT_DIR / "layer2_vectors.npz",
        vectors=projected,
        track_ids=np.asarray(track_ids),
        paths=paths_array,
    )
    (ARTIFACT_DIR / "training_history.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"완료: {len(paths)}개 구간 학습 | 결과: {ARTIFACT_DIR}")
    print("저장 파일: layer2_metric_head.pt, layer2_vectors.npz, clap_embeddings.npz, segment_manifest.csv")


if __name__ == "__main__":
    main()
