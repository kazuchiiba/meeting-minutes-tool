"""pyannote で話者分離し、transcribe.py の結果に話者を付ける。

事前準備:
    Hugging Face で次の2モデルの利用規約に同意し、トークン(read)を `hf auth login` で保存する
    (または環境変数 HF_TOKEN に設定する)。
      https://huggingface.co/pyannote/speaker-diarization-3.1
      https://huggingface.co/pyannote/segmentation-3.0

使い方:
    .venv-diar/Scripts/python src/diarize.py INPUT/xxx.m4a [--speakers N] [--step 0.1] [--min-cluster-size N]
    (pyannote は faster-whisper と依存が衝突するので、専用の .venv-diar で動かす)
    --step / --min-cluster-size は、run_pipeline.py から実行すると setting/setting.xlsx の値が渡される。

入力: transcripts/<name>.json (transcribe.py の出力)
出力 (transcripts/ 配下):
    <name>.diarization.json  話者区間の生データ
    <name>.speakers.txt      [時刻] SPEAKER_xx: テキスト (議事録作成の入力に使う)
    <name>.meta.json         話者分離の設定・処理時間（工程別）を追記
"""

import argparse
import json
import os
import time
from pathlib import Path

import torch
from pyannote.audio import Pipeline

from audio_io import SAMPLE_RATE, load_audio
from diar_timing import DEFAULT_STEP, StageTimer, configure
from merge_speakers import merge
from paths import transcript_stem

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "transcripts"
PIPELINE = "pyannote/speaker-diarization-3.1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--speakers", type=int, default=None, help="参加人数が分かっていれば指定")
    parser.add_argument("--name", default=None, help="出力先の名前（既定は音声ファイル名。比較用に分けるときに使う）")
    parser.add_argument("--step", type=float, default=DEFAULT_STEP, help="窓をずらす幅（窓の長さ 10秒に対する割合）")
    parser.add_argument("--min-cluster-size", type=int, default=None, help="1話者あたりの最低特徴量数（省略時はずらし幅から自動）")
    args = parser.parse_args()

    stem = transcript_stem(args.name or args.audio.stem)

    started = time.time()
    # HF_TOKEN がなければ `hf auth login` で保存したトークンを使う
    pipeline = Pipeline.from_pretrained(PIPELINE, use_auth_token=os.environ.get("HF_TOKEN") or True)
    pipeline.to(torch.device("cpu"))
    min_cluster_size = configure(pipeline, args.step, args.min_cluster_size)
    waveform = torch.from_numpy(load_audio(args.audio)).unsqueeze(0)
    timer = StageTimer()
    diarization = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE}, num_speakers=args.speakers, hook=timer)
    elapsed = time.time() - started
    stages = {"モデル・音声の読み込み": round(timer.started - started, 1), **timer.stages}

    turns = [
        {"start": round(turn.start, 2), "end": round(turn.end, 2), "speaker": spk}
        for turn, _, spk in diarization.itertracks(yield_label=True)
    ]
    Path(f"{stem}.diarization.json").write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")

    merge(stem)

    meta_path = Path(f"{stem}.meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["diarization"] = {
        "tool": PIPELINE,
        "num_speakers": args.speakers,
        "segmentation_step": args.step,
        "min_cluster_size": min_cluster_size,
        "detected_speakers": sorted({t["speaker"] for t in turns}),
        "elapsed_sec": round(elapsed, 1),
        "stages_sec": stages,
    }
    meta["note"] = "話者は SPEAKER_xx の記号。氏名との対応は未付与。文字起こしは無修正。"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done: {len(turns)} turns, speakers={meta['diarization']['detected_speakers']}, {elapsed / 60:.1f} min")


if __name__ == "__main__":
    main()
