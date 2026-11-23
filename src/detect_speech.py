"""pyannote の区間検出（segmentation-3.0）だけで発話区間を求める。声の特徴量・話者のまとめ（話者分離）はしない。

話者分離をしない会議で、③抜けの補完が使う発話区間を、Silero VAD の代わりに pyannote で求めるために使う
（docs/issue/issue_md/ISSUE-026。子会社X定例会で、話者分離ありの補完の方が抜けが少なかった）。
話者分離の②のうち最初の「区間検出」（約1分）にあたり、声の特徴量（約44分）は計算しない。

使い方（.venv-diar で。HF_TOKEN または `hf auth login` が必要。diarize.py と同じ）:
    .venv-diar/Scripts/python src/detect_speech.py INPUT/xxx.m4a [--name 名前]

出力: transcripts/<名前>/<名前>.speech.json（[{start, end, speaker: "SPEECH"}]）。
fill_gaps.py --no-diarize は、このファイルがあれば Silero VAD の代わりに使う。
"""

import argparse
import json
import os
import time
from pathlib import Path

import torch
from pyannote.audio import Model
from pyannote.audio.pipelines import VoiceActivityDetection

from audio_io import SAMPLE_RATE, load_audio
from paths import transcript_stem

SEGMENTATION = "pyannote/segmentation-3.0"
PARAMS = {"min_duration_on": 0.0, "min_duration_off": 0.0}  # pyannote の推奨値（segmentation-3.0）


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--name", default=None, help="出力先の名前（既定は音声ファイル名）")
    args = parser.parse_args()

    stem = transcript_stem(args.name or args.audio.stem)
    started = time.time()
    model = Model.from_pretrained(SEGMENTATION, use_auth_token=os.environ.get("HF_TOKEN") or True)
    pipeline = VoiceActivityDetection(segmentation=model)
    pipeline.instantiate(PARAMS)
    waveform = torch.from_numpy(load_audio(args.audio)).unsqueeze(0)
    speech = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE})
    elapsed = time.time() - started

    spans = [{"start": round(s.start, 2), "end": round(s.end, 2), "speaker": "SPEECH"} for s in speech.get_timeline().support()]
    Path(f"{stem}.speech.json").write_text(json.dumps(spans, ensure_ascii=False, indent=1), encoding="utf-8")

    meta_path = Path(f"{stem}.meta.json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["speech_detection"] = {
            "tool": f"{SEGMENTATION}（VoiceActivityDetection）",
            "params": PARAMS,
            "spans": len(spans),
            "speech_sec": round(sum(s["end"] - s["start"] for s in spans), 1),
            "elapsed_sec": round(elapsed, 1),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done: {len(spans)} spans, speech {sum(s['end'] - s['start'] for s in spans) / 60:.1f} min, {elapsed / 60:.1f} min")


if __name__ == "__main__":
    main()
