"""工程の開始・終了を transcripts/<名前>/<名前>.timing.json に記録する（④〜⑦の Claude の作業時間の計測用）。

run_pipeline.py が①〜③を記録したファイルに、同じ形式で追記する。

使い方:
    .venv/Scripts/python src/timing.py <名前> start "④ 議事録の作成"
    .venv/Scripts/python src/timing.py <名前> end   "④ 議事録の作成"
    .venv/Scripts/python src/timing.py <名前> show
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from paths import transcript_stem

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="音声ファイル名（拡張子なし）")
    parser.add_argument("action", choices=["start", "end", "show"])
    parser.add_argument("step", nargs="?", default="")
    args = parser.parse_args()

    path = transcript_stem(args.name).with_name(f"{args.name}.timing.json")
    timing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"audio": args.name, "steps": []}
    now = datetime.now()

    if args.action == "start":
        timing["steps"].append({"step": args.step, "start": now.isoformat(timespec="seconds")})
    elif args.action == "end":
        step = next(s for s in reversed(timing["steps"]) if s["step"] == args.step and "end" not in s)
        step["end"] = now.isoformat(timespec="seconds")
        step["elapsed_min"] = round((now - datetime.fromisoformat(step["start"])).total_seconds() / 60, 1)
    path.write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.action == "show" or args.action == "end":
        for s in timing["steps"]:
            print(f"{s['step']:<14} {s.get('elapsed_min', '実行中'):>6} 分  ({s['start']} 〜 {s.get('end', '')})")
        print(f"合計 {sum(s.get('elapsed_min', 0) for s in timing['steps']):.1f} 分")


if __name__ == "__main__":
    main()
