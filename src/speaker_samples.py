"""話者対応表を作るために、話者記号ごとの発話量と発言例を表示する。

使い方:
    .venv/Scripts/python src/speaker_samples.py transcripts/<名前>/<名前>.json [--n 8]
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from merge_speakers import fmt_ts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path, help="transcripts/<名前>/<名前>.json（話者付き）")
    parser.add_argument("--n", type=int, default=8, help="話者ごとに表示する発言例の数")
    args = parser.parse_args()

    segments = json.loads(args.transcript.read_text(encoding="utf-8"))
    by_speaker = defaultdict(list)
    for seg in segments:
        by_speaker[seg.get("speaker", "不明")].append(seg)

    print(f"# 話者ごとの発言例：{args.transcript.name}\n")
    for spk, segs in sorted(by_speaker.items(), key=lambda kv: -sum(s["end"] - s["start"] for s in kv[1])):
        total = sum(s["end"] - s["start"] for s in segs)
        print(f"## {spk}（発話 {total / 60:.1f}分、{len(segs)} セグメント）")
        # 名前の呼びかけ・自己紹介が出やすいので、冒頭と長めの発言を優先して並べる
        picks = segs[:3] + sorted(segs[3:], key=lambda s: -len(s["text"]))[: max(0, args.n - 3)]
        for s in sorted(picks, key=lambda s: s["start"]):
            print(f"- [{fmt_ts(s['start'])}] {s['text'][:80]}")
        print()


if __name__ == "__main__":
    main()
