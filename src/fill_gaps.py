"""Whisper が取りこぼした発話を補う。

次の2種類の「抜け」を探し、pyannote が発話を検出した部分だけを VAD なしで文字起こしし直す。
  1. 疎なセグメント: 長いのに文字数が極端に少ない (デコードが崩れて最後の一言だけ残ったもの)。置き換える。
     例: 11/20 CI の 21:22–22:34 (72秒) が「承知です。」の5文字だけになっていた
  2. 空白区間: pyannote は発話を検出しているのに、Whisper のセグメントがほとんどない。追加する。
最後に話者を割り当て直す。

使い方 (diarize.py の後に):
    .venv/Scripts/python src/fill_gaps.py INPUT/xxx.m4a
"""

import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel

from audio_io import SAMPLE_RATE, load_audio
from merge_speakers import fmt_ts, merge
from paths import transcript_stem
from transcribe import SETTINGS

MERGE_GAP = 1.0  # この秒数以内の話者区間はつなげて1つの発話区間とみなす
MIN_SPAN = 3.0  # これより短い区間は補わない
MAX_COVERAGE = 0.2  # Whisper のセグメントが区間のこの割合未満しか覆っていなければ「抜け」とみなす
PAD = 0.5
SPARSE_MIN_SEC = 10.0  # 疎なセグメントとみなす最小の長さ
SPARSE_MAX_CPS = 1.5  # 1秒あたりの文字数がこれ未満なら疎とみなす (通常の日本語の発話は 5〜8 字/秒)


def speech_spans(turns: list[dict]) -> list[tuple[float, float]]:
    spans: list[list[float]] = []
    for t in sorted(turns, key=lambda t: t["start"]):
        if spans and t["start"] - spans[-1][1] <= MERGE_GAP:
            spans[-1][1] = max(spans[-1][1], t["end"])
        else:
            spans.append([t["start"], t["end"]])
    return [(s, e) for s, e in spans if e - s >= MIN_SPAN]


def coverage(start: float, end: float, segments: list[dict]) -> float:
    covered = sum(max(0.0, min(end, s["end"]) - max(start, s["start"])) for s in segments)
    return covered / (end - start)


def is_sparse(seg: dict) -> bool:
    dur = seg["end"] - seg["start"]
    return dur >= SPARSE_MIN_SEC and len(seg["text"]) / dur < SPARSE_MAX_CPS


def speech_within(start: float, end: float, turns: list[dict]) -> tuple[float, float] | None:
    """区間内で pyannote が発話を検出した最初から最後まで。発話がなければ None。"""
    inside = [t for t in turns if t["end"] > start and t["start"] < end]
    if not inside:
        return None
    return max(start, min(t["start"] for t in inside)), min(end, max(t["end"] for t in inside))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--name", default=None, help="出力先の名前（既定は音声ファイル名）")
    parser.add_argument("--no-diarize", action="store_true",
                        help="話者分離なし：疎なセグメントの区間全体を VAD ありで文字起こしし直す（無音からの幻覚を避ける）")
    parser.add_argument("--hotwords", default=None, help="Whisper に渡す語（docs/issue/issue_md/ISSUE-025）")
    args = parser.parse_args()

    stem = transcript_stem(args.name or args.audio.stem)
    segments = [s for s in json.loads(stem.with_suffix(".json").read_text(encoding="utf-8")) if not s.get("filled")]
    turns = [] if args.no_diarize else json.loads(Path(f"{stem}.diarization.json").read_text(encoding="utf-8"))

    sparse = [s for s in segments if is_sparse(s)]
    segments = [s for s in segments if not is_sparse(s)]
    if args.no_diarize:
        targets = [((seg["start"], seg["end"]), seg) for seg in sparse]
    else:
        targets = [(span, seg) for seg in sparse if (span := speech_within(seg["start"], seg["end"], turns))]
        targets += [((s, e), None) for s, e in speech_spans(turns) if coverage(s, e, segments + sparse) < MAX_COVERAGE]
    print(f"sparse segments: {len(sparse)}, targets: {len(targets)}")

    added = []
    if targets:
        audio = load_audio(args.audio)
        model = WhisperModel(SETTINGS["model"], device=SETTINGS["device"], compute_type=SETTINGS["compute_type"])
        for (s, e), original in targets:
            offset = max(0.0, s - PAD)
            clip = audio[int(offset * SAMPLE_RATE) : int((e + PAD) * SAMPLE_RATE)]
            result, _ = model.transcribe(
                clip,
                language=SETTINGS["language"],
                beam_size=SETTINGS["beam_size"],
                vad_filter=args.no_diarize,  # 話者分離なしでは発話区間が分からないので VAD で無音を除く
                condition_on_previous_text=False,
                hotwords=args.hotwords,
            )
            new = [
                {"start": offset + r.start, "end": offset + r.end, "text": r.text.strip(), "filled": True}
                for r in result
                if r.text.strip()
            ]
            print(f"[{fmt_ts(s)}-{fmt_ts(e)}] {'置換: ' + original['text'] if original else '追加'} -> {len(new)} segments")
            if original and not new:
                new = [original]  # 再文字起こしで何も出なければ元に戻す
            added += new
        # 発話のない疎なセグメント (冒頭の待ち時間など) はそのまま残す
        replaced = {id(o) for _, o in targets if o}
        added += [s for s in sparse if id(s) not in replaced]
    else:
        added = sparse

    segments = sorted(segments + added, key=lambda x: x["start"])
    for i, seg in enumerate(segments, 1):
        seg["id"] = i
    stem.with_suffix(".json").write_text(json.dumps(segments, ensure_ascii=False, indent=1), encoding="utf-8")
    stem.with_suffix(".txt").write_text(
        "\n".join(f"[{fmt_ts(r['start'])}] {r['text']}" for r in segments) + "\n", encoding="utf-8"
    )
    if args.no_diarize:  # 話者記号なし。議事録作成の入力として同じ名前のファイルを作る
        Path(f"{stem}.speakers.txt").write_text(stem.with_suffix(".txt").read_text(encoding="utf-8"), encoding="utf-8")
    else:
        merge(stem)

    meta_path = Path(f"{stem}.meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["gap_fill"] = {
        "reason": "Whisper が長い区間を数文字に潰す・発話区間を出力しないことがある",
        "rule": (
            f"話者分離なし：{SPARSE_MIN_SEC}秒以上で {SPARSE_MAX_CPS}字/秒未満のセグメントの区間全体を VAD ありで再文字起こし"
            if args.no_diarize else
            f"(1) {SPARSE_MIN_SEC}秒以上で {SPARSE_MAX_CPS}字/秒未満のセグメントを置換、"
            f"(2) pyannote の発話区間({MIN_SPAN}秒以上)で Whisper の被覆率 {MAX_COVERAGE:.0%} 未満の区間を追加。"
            "いずれも pyannote の発話部分だけを VAD なしで再文字起こし"
        ),
        "spans": [[fmt_ts(s), fmt_ts(e), "置換" if o else "追加"] for (s, e), o in targets],
        "segments_from_refill": sum(1 for s in added if s.get("filled")),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done: {sum(1 for s in added if s.get('filled'))} refilled segments")


if __name__ == "__main__":
    main()
