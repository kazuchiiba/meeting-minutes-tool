"""話者分離の窓をずらす幅（segmentation_step）ごとに、処理時間と精度の落ち方を比べる（ISSUE-018）。

pyannote は 10秒の窓を既定で 1秒（step=0.1）ずつずらす。幅を広げると窓の数がほぼ反比例で減り速くなるが、
精度が落ちる可能性がある。正解の話者ラベルはないので、既定の step=0.1 の結果を基準として、どれだけずれるかを見る。

使い方（プロジェクトルートで。重い処理なので他の処理と同時に動かさない。出力は logs/diar_step_eval_<名前>.log に残す）:
    .venv-diar/Scripts/python src/diar_step_eval.py INPUT/xxx.m4a --speakers N [--steps 0.1 0.2 0.3 0.5]
        [--start 22:45 --duration 5:00]   一部の区間だけで比べる（※5分では話者のまとめ方が全体と変わり、比較にならなかった）
        [--ref transcripts/<名前>/<名前>.diarization.json --ref-ratio 1.9]
                                          既存の step=0.1 の結果を基準に使い、0.1 の再計算を省く（処理時間は音声比で与える）
        [--auto-min-cluster]              1話者あたりの最低特徴量数を、ずらし幅に合わせて縮める（diar_timing.auto_min_cluster_size）

出力（transcripts/<名前>/step_eval/ 配下。区間を指定した場合は step_eval/<開始>+<長さ>/ 配下）:
    step<幅>[_mcs<最低数>].diarization.json  幅ごとの話者区間（あれば計算を飛ばして再利用する）
    step<幅>[_mcs<最低数>].timing.json       工程別の処理時間
    report.md / report.json    比較表

指標（いずれも step=0.1 の結果との比較）:
    DER        話者区間のずれ（pyannote.metrics。話者の取り違え・発話の見落とし・誤検出の合計の割合）
    発話一致率  Whisper の各発話に付く話者が基準と同じ割合（議事録に直接効く指標。発話の長さで重み付け）
"""

import argparse
import ctypes
import json
import os
import time
from pathlib import Path

import numpy as np
import torch
from pyannote.audio import Pipeline
from pyannote.core import Annotation, Segment
from pyannote.metrics.diarization import DiarizationErrorRate
from scipy.optimize import linear_sum_assignment

from audio_io import SAMPLE_RATE, load_audio
from diar_timing import DEFAULT_MIN_CLUSTER_SIZE, StageTimer, auto_min_cluster_size, configure
from diarize import PIPELINE
from merge_speakers import assign_speaker
from paths import transcript_stem


def keep_awake(on: bool) -> None:
    """長時間の実験中に Windows がスリープしないようにする（run_pipeline.py と同じ。.venv-diar から読めるよう複製）。"""
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))


def to_annotation(turns: list[dict]) -> Annotation:
    ann = Annotation()
    for i, t in enumerate(turns):
        ann[Segment(t["start"], t["end"]), i] = t["speaker"]
    return ann


def segment_agreement(segments: list[dict], ref: list[dict], hyp: list[dict]) -> float:
    """Whisper の発話ごとの話者が基準と一致する割合（発話の長さで重み付け。話者記号は最適に対応付ける）。"""
    pairs = [(assign_speaker(s["start"], s["end"], ref), assign_speaker(s["start"], s["end"], hyp), s["end"] - s["start"])
             for s in segments]
    ref_labels = sorted({p[0] for p in pairs})
    hyp_labels = sorted({p[1] for p in pairs})
    table = np.zeros((len(ref_labels), len(hyp_labels)))
    for r, h, dur in pairs:
        table[ref_labels.index(r), hyp_labels.index(h)] += dur
    rows, cols = linear_sum_assignment(-table)
    return table[rows, cols].sum() / table.sum()


def parse_ts(text: str) -> float:
    """'22:45' / '1:02:03' / '1365' を秒にする。"""
    sec = 0.0
    for part in text.split(":"):
        sec = sec * 60 + float(part)
    return sec


def variant_key(step: float, mcs: int) -> str:
    return f"step{step}" if mcs == DEFAULT_MIN_CLUSTER_SIZE else f"step{step}_mcs{mcs}"


def run(pipeline, waveform, step: float, mcs: int, speakers: int | None, out: Path) -> dict:
    configure(pipeline, step, mcs)
    key = variant_key(step, mcs)
    print(f"[{key}] 開始（窓のずらし幅 {step * 10:.1f}秒、最低特徴量数 {mcs}）", flush=True)
    timer = StageTimer()
    started = time.time()
    diarization = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE}, num_speakers=speakers, hook=timer)
    elapsed = time.time() - started
    turns = [
        {"start": round(turn.start, 2), "end": round(turn.end, 2), "speaker": spk}
        for turn, _, spk in diarization.itertracks(yield_label=True)
    ]
    (out / f"{key}.diarization.json").write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
    timing = {"step": step, "min_cluster_size": mcs, "elapsed_sec": round(elapsed, 1), "stages_sec": timer.stages}
    (out / f"{key}.timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{key}] 終了：{elapsed / 60:.1f}分", flush=True)
    return timing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--speakers", type=int, default=None, help="参加人数")
    parser.add_argument("--steps", type=float, nargs="+", default=[0.1, 0.2, 0.3, 0.5])
    parser.add_argument("--start", default=None, help="比べる区間の開始（例 22:45）。省略時は音声全体")
    parser.add_argument("--duration", default="5:00", help="比べる区間の長さ（--start と一緒に使う）")
    parser.add_argument("--ref", type=Path, default=None, help="基準に使う既存の step=0.1 の diarization.json")
    parser.add_argument("--ref-ratio", type=float, default=None, help="--ref の処理時間（音声の何倍か）")
    parser.add_argument("--auto-min-cluster", action="store_true", help="最低特徴量数をずらし幅に合わせて縮める")
    args = parser.parse_args()
    steps = sorted(set(args.steps) | {0.1})  # 0.1 は比較の基準なので必ず含める
    variants = [(s, auto_min_cluster_size(s) if args.auto_min_cluster else DEFAULT_MIN_CLUSTER_SIZE) for s in steps]

    stem = transcript_stem(args.audio.stem)
    out = stem.parent / "step_eval"
    clip = None
    if args.start:
        clip = (parse_ts(args.start), parse_ts(args.start) + parse_ts(args.duration))
        out = out / f"{args.start.replace(':', '')}+{args.duration.replace(':', '')}"
    out.mkdir(parents=True, exist_ok=True)
    audio_sec = None

    if args.ref and not (out / "step0.1.diarization.json").exists():
        assert not args.start, "--ref は音声全体の比較でだけ使える"
        (out / "step0.1.diarization.json").write_text(args.ref.read_text(encoding="utf-8"), encoding="utf-8")
        audio_dur = json.loads(Path(f"{stem}.meta.json").read_text(encoding="utf-8"))["audio_duration_sec"]
        timing = {"step": 0.1, "min_cluster_size": DEFAULT_MIN_CLUSTER_SIZE, "stages_sec": {},
                  "elapsed_sec": round(args.ref_ratio * audio_dur, 1), "note": f"{args.ref.name} を再利用。処理時間は音声の {args.ref_ratio}倍として推定"}
        (out / "step0.1.timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")

    todo = [(s, m) for s, m in variants if not (out / f"{variant_key(s, m)}.diarization.json").exists()]
    if todo:
        pipeline = Pipeline.from_pretrained(PIPELINE, use_auth_token=True)
        pipeline.to(torch.device("cpu"))
        audio = load_audio(args.audio)
        if clip:
            audio = audio[int(clip[0] * SAMPLE_RATE):int(clip[1] * SAMPLE_RATE)]
        audio_sec = len(audio) / SAMPLE_RATE
        waveform = torch.from_numpy(audio).unsqueeze(0)
        keep_awake(True)
        try:
            for step, mcs in todo:
                run(pipeline, waveform, step, mcs, args.speakers, out)
        finally:
            keep_awake(False)

    segments = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
    if clip:
        # 区間内の発話だけを、区間の先頭を 0 秒とした時刻にして使う
        segments = [dict(s, start=s["start"] - clip[0], end=s["end"] - clip[0])
                    for s in segments if s["start"] >= clip[0] and s["end"] <= clip[1]]
        audio_sec = clip[1] - clip[0]
    elif audio_sec is None:
        audio_sec = json.loads(Path(f"{stem}.meta.json").read_text(encoding="utf-8"))["audio_duration_sec"]
    ref_turns = json.loads((out / "step0.1.diarization.json").read_text(encoding="utf-8"))
    ref = to_annotation(ref_turns)
    base = json.loads((out / "step0.1.timing.json").read_text(encoding="utf-8"))
    base_sec = base["elapsed_sec"]

    rows = []
    for step, mcs in variants:
        key = variant_key(step, mcs)
        turns = json.loads((out / f"{key}.diarization.json").read_text(encoding="utf-8"))
        timing = json.loads((out / f"{key}.timing.json").read_text(encoding="utf-8"))
        der = DiarizationErrorRate()(ref, to_annotation(turns), detailed=True)
        total = der["total"] or 1.0
        rows.append({
            "step": step,
            "shift_sec": round(step * 10, 1),
            "min_cluster_size": mcs,
            "elapsed_min": round(timing["elapsed_sec"] / 60, 1),
            "x_realtime": round(timing["elapsed_sec"] / audio_sec, 2),
            "speedup": round(base_sec / timing["elapsed_sec"], 1),
            "stages_min": {k: round(v / 60, 1) for k, v in timing["stages_sec"].items()},
            "speakers": len({t["speaker"] for t in turns}),
            "der_pct": round(100 * der["diarization error rate"], 1),
            "confusion_pct": round(100 * der["confusion"] / total, 1),
            "missed_pct": round(100 * der["missed detection"] / total, 1),
            "false_alarm_pct": round(100 * der["false alarm"] / total, 1),
            "segment_agreement_pct": round(100 * segment_agreement(segments, ref_turns, turns), 1),
        })

    report = "report_auto_mcs" if args.auto_min_cluster else "report"
    (out / f"{report}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    stage_names = list(dict.fromkeys(n for r in rows for n in r["stages_min"]))
    lines = [
        f"# 話者分離の窓幅の比較：{args.audio.stem}",
        "",
        (f"区間 {args.start} から {args.duration}（発話 {len(segments)}個）、" if clip else "")
        + f"音声 {audio_sec / 60:.1f}分、参加人数指定 {args.speakers}。精度は step=0.1（pyannote の既定）の結果との比較。",
        *([f"基準：{base['note']}"] if "note" in base else []),
        "",
        "| step | ずらし幅 | 最低特徴量数 | 処理時間 | 音声比 | 速さ | 話者数 | DER | うち取り違え | 見落とし | 誤検出 | 発話一致率 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['step']} | {r['shift_sec']}秒 | {r['min_cluster_size']} | {r['elapsed_min']}分 | {r['x_realtime']}倍 | {r['speedup']}倍 | {r['speakers']} "
            f"| {r['der_pct']}% | {r['confusion_pct']}% | {r['missed_pct']}% | {r['false_alarm_pct']}% | {r['segment_agreement_pct']}% |"
        )
    lines += ["", "工程別の処理時間（分）", "", "| step | " + " | ".join(stage_names) + " |",
              "|---|" + "---|" * len(stage_names)]
    for r in rows:
        lines.append(f"| {r['step']} | " + " | ".join(str(r["stages_min"].get(n, "")) for n in stage_names) + " |")
    (out / f"{report}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
