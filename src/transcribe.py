"""音声ファイルを faster-whisper で文字起こしする。

使い方:
    .venv/Scripts/python src/transcribe.py INPUT/xxx.m4a [INPUT/yyy.m4a ...]

出力 (transcripts/<名前>/ 配下。<名前> は音声ファイル名):
    <name>.txt       タイムスタンプ付きテキスト (議事録作成の入力に使う)
    <name>.srt       字幕形式 (音声と突き合わせる用)
    <name>.json      セグメント単位の生データ
    <name>.meta.json 文字起こし手段・設定の記録 (検証計画 3.1)
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from faster_whisper import WhisperModel, __version__ as FW_VERSION

from audio_io import load_audio
from paths import transcript_stem

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "transcripts"

SETTINGS = {
    "model": "large-v3-turbo",
    "device": "cpu",
    "compute_type": "int8",
    "language": "ja",
    "beam_size": 5,
    "vad_filter": True,
    # 前の文脈を引き継ぐと長時間音声で同じ文の繰り返し(幻覚)が起きやすいので切る
    "condition_on_previous_text": False,
}


def fmt_ts(sec: float, srt: bool = False) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    if srt:
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
    return f"{h:02}:{m:02}:{s:02}"


def transcribe(model: WhisperModel, audio: Path, name: str | None = None, hotwords: str | None = None) -> None:
    """name：出力先の名前（既定は音声ファイル名。話者分離なしの比較用などで変える）
    hotwords：Whisper に渡す語（参加者名・用語集。docs/issue/issue_md/ISSUE-025）。None なら渡さない
    """
    started = time.time()
    segments, info = model.transcribe(
        load_audio(audio),
        language=SETTINGS["language"],
        beam_size=SETTINGS["beam_size"],
        vad_filter=SETTINGS["vad_filter"],
        condition_on_previous_text=SETTINGS["condition_on_previous_text"],
        hotwords=hotwords,
    )

    rows = []
    for seg in segments:
        rows.append({"id": len(rows) + 1, "start": seg.start, "end": seg.end, "text": seg.text.strip()})
        print(f"[{audio.stem}] {fmt_ts(seg.end)} / {fmt_ts(info.duration)}  {seg.text.strip()}", flush=True)

    elapsed = time.time() - started
    stem = transcript_stem(name or audio.stem)

    stem.with_suffix(".txt").write_text(
        "\n".join(f"[{fmt_ts(r['start'])}] {r['text']}" for r in rows) + "\n", encoding="utf-8"
    )
    stem.with_suffix(".srt").write_text(
        "\n".join(
            f"{r['id']}\n{fmt_ts(r['start'], True)} --> {fmt_ts(r['end'], True)}\n{r['text']}\n" for r in rows
        ),
        encoding="utf-8",
    )
    stem.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(f"{stem}.meta.json").write_text(
        json.dumps(
            {
                "audio": audio.name,
                "tool": f"faster-whisper {FW_VERSION}",
                "settings": SETTINGS,
                "hotwords": hotwords,  # Whisper に渡した語（処理時間への影響を見るために記録）
                "audio_duration_sec": round(info.duration, 1),
                "elapsed_sec": round(elapsed, 1),
                "segments": len(rows),
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "note": "話者分離なし。文字起こしは無修正。",
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"[{audio.stem}] done: {len(rows)} segments, {elapsed / 60:.1f} min", flush=True)


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    model = WhisperModel(SETTINGS["model"], device=SETTINGS["device"], compute_type=SETTINGS["compute_type"])
    args = sys.argv[1:]
    opts = {"--name": None, "--hotwords": None}  # --name：出力先の名前（音声1つのとき）、--hotwords：Whisper に渡す語
    for key in opts:
        if key in args:
            i = args.index(key)
            opts[key] = args[i + 1]
            args = args[:i] + args[i + 2 :]
    for arg in args:
        transcribe(model, Path(arg), opts["--name"], opts["--hotwords"])


if __name__ == "__main__":
    main()
