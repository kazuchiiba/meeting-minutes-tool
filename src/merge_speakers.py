"""Whisper のセグメントに、pyannote の話者区間から話者を割り当てる。

diarize.py (.venv-diar) と fill_gaps.py (.venv) の両方から使うので、torch などに依存しない。
"""

import json
from pathlib import Path


def fmt_ts(sec: float) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02}:{m:02}:{s:02}"


def assign_speaker(start: float, end: float, turns: list[dict]) -> str:
    """セグメントと最も長く重なる話者を返す。重なりがなければ最寄りの話者。"""
    overlap: dict[str, float] = {}
    for t in turns:
        o = min(end, t["end"]) - max(start, t["start"])
        if o > 0:
            overlap[t["speaker"]] = overlap.get(t["speaker"], 0.0) + o
    if overlap:
        return max(overlap, key=overlap.get)
    mid = (start + end) / 2
    return min(turns, key=lambda t: min(abs(mid - t["start"]), abs(mid - t["end"])))["speaker"]


def merge(stem: Path) -> None:
    """<stem>.json に speaker を付け、<stem>.speakers.txt を書き出す。"""
    segments = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
    turns = json.loads(Path(f"{stem}.diarization.json").read_text(encoding="utf-8"))

    for seg in segments:
        seg["speaker"] = assign_speaker(seg["start"], seg["end"], turns)
    stem.with_suffix(".json").write_text(json.dumps(segments, ensure_ascii=False, indent=1), encoding="utf-8")

    # 同じ話者が続く間は1行にまとめる
    lines, cur = [], None
    for seg in segments:
        if cur and cur["speaker"] == seg["speaker"]:
            cur["text"] += " " + seg["text"]
        else:
            cur = {"start": seg["start"], "speaker": seg["speaker"], "text": seg["text"]}
            lines.append(cur)
    Path(f"{stem}.speakers.txt").write_text(
        "\n".join(f"[{fmt_ts(l['start'])}] {l['speaker']}: {l['text']}" for l in lines) + "\n", encoding="utf-8"
    )
