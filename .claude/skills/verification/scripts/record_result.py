"""1回の評価（テスト）の結果を JSON に記録する。

既にある出力ファイルから数値を機械的に集めるので、Claude が中身を読む必要はない。
人手版との比較（検証計画 4.3 の指標）と所見は、--set / --note で後から追記する。

使い方（プロジェクトルートで）:
    # 新しい評価を記録（run_id を表示する）
    .venv/Scripts/python .claude/skills/verification/scripts/record_result.py <名前> --label 追加試行
    # 既存の評価に、人手版との比較や所見を追記する
    .venv/Scripts/python .claude/skills/verification/scripts/record_result.py <名前> --run <run_id> \
        --set 付け足し=0 --set 話者誤り=2 --note "見出しの区切りが人手版と違う（ISSUE-003）"

出力:
    docs/verification/results/<run_id>.json   run_id = YYYYMMDD-HHMM_<名前>
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RESULTS = ROOT / "docs" / "verification" / "results"
GLOSSARY = ROOT / "docs" / "design" / "議事録作成用の用語集.xlsx"

# 人手版との比較（docs/verification/議事録検証計画.md 4.3）。人が判定して --set で入れる
MANUAL_KEYS = ["付け足し", "確度の格上げ", "無断推定", "話者誤り", "網羅数", "キーポイント数", "人手版文字数"]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def minutes_stats(md_path: Path) -> dict:
    if not md_path.exists():
        return {}
    md = md_path.read_text(encoding="utf-8")
    body = [l.strip() for l in md.splitlines() if l.strip() and not l.startswith((">", "|", "#"))]
    section, decisions, todos = None, 0, 0
    for line in md.splitlines():
        s = line.strip()
        if re.fullmatch(r"【[^】]{1,10}】", s):
            section = s
        elif s.startswith("- ") and section == "【決定事項】" and "なし" not in s:
            decisions += 1
        elif s.startswith("- ") and section == "【TODO】":
            todos += 1
    text = "".join(body)
    return {
        "文字数": len(re.sub(r"【[^】]*】", "", text)),
        "段落数": len(body),
        "見出し数": len(re.findall(r"^## ", md, re.M)),
        "決定事項数": decisions,
        "TODO数": todos,
        "画像枠数": md.count("[("),
        "推定": len(re.findall(r"【推定", md)),
        "聞き取り不明": len(re.findall(r"【聞き取り不明", md)),
        "要確認": len(re.findall(r"【要確認", md)),
    }


def glossary_candidates(minutes_name: str) -> int | None:
    if not GLOSSARY.exists():
        return None
    from openpyxl import load_workbook

    wb = load_workbook(GLOSSARY, read_only=True)
    if "候補" not in wb.sheetnames:
        return 0
    return sum(1 for r in wb["候補"].iter_rows(min_row=2, values_only=True) if r[5] and minutes_name in str(r[5]))


def collect(name: str, minutes_file: str) -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from paths import transcript_stem

    stem = transcript_stem(name)
    meta = load_json(stem.with_name(f"{name}.meta.json")) or {}
    timing = load_json(stem.with_name(f"{name}.timing.json")) or {}
    folder = ROOT / "output_MeetingMinutes" / name / "evidence_log"  # 議事録 md・自己点検の結果の置き場所
    if not (folder / minutes_file).exists() and (folder.parent / minutes_file).exists():
        folder = folder.parent  # evidence_log/ 導入前の配置
    check = load_json((folder / minutes_file).with_suffix(".check.json")) or {}
    sys.path.insert(0, str(ROOT / "src"))
    info = {}
    info_file = next((p for p in (ROOT / "INPUT").glob(f"{name}.会議情報.txt")), None)
    if info_file:
        from meeting_info import parse

        info = parse(info_file.read_text(encoding="utf-8"))

    steps = {s["step"]: s.get("elapsed_min") for s in timing.get("steps", [])}
    if not steps and meta:  # run_pipeline.py 導入前の会議は meta.json の処理時間を使う
        steps = {
            "① 文字起こし": round(meta.get("elapsed_sec", 0) / 60, 1) or None,
            "② 話者分離": round(meta.get("diarization", {}).get("elapsed_sec", 0) / 60, 1) or None,
        }
    speaker_map = info.get("話者対応表", {})
    return {
        "会議": {
            "名前": name,
            "会議名": info.get("会議名") or name,  # 空欄なら入力ファイル名
            "会議の種類": info.get("会議の種類", ""),
            "参加者数": len(info.get("参加者", [])),
            "音声の長さ_分": round(meta.get("audio_duration_sec", 0) / 60, 1),
        },
        "処理時間_分": steps,
        "文字起こし": {
            "セグメント数": meta.get("segments"),
            "検出話者数": len(meta.get("diarization", {}).get("detected_speakers", [])),
            "補完セグメント数": meta.get("gap_fill", {}).get("segments_from_refill"),
            "話者対応表": "記入なし" if not speaker_map else
                          ("AI推定あり" if any("AI推定" in v for v in speaker_map.values()) else "記録者が記入"),
        },
        "議事録ファイル": str((folder / minutes_file).relative_to(ROOT)).replace("\\", "/"),
        "議事録": minutes_stats(folder / minutes_file),
        "自己点検": {"抜けの候補": check.get("gap_candidates"), "根拠のない語の候補": check.get("unsupported_candidates")},
        "用語集の追加候補": glossary_candidates(minutes_file),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="音声ファイル名（拡張子なし）")
    parser.add_argument("--label", default="", help="評価の区分（基本試行 / 追加試行 / 本番 など）")
    parser.add_argument("--run", default=None, help="追記する既存の run_id")
    parser.add_argument("--minutes", default=None, help="評価する議事録 md（既定：output_MeetingMinutes/<名前>/evidence_log/<名前>_議事録.md）")
    parser.add_argument("--set", action="append", default=[], help="人手版との比較など 指標=値")
    parser.add_argument("--note", action="append", default=[], help="所見（Issue 番号があれば含める）")
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    if args.run:
        path = RESULTS / f"{args.run}.json"
        result = load_json(path)
        if result is None:
            sys.exit(f"見つかりません：{path}")
    else:
        suffix = f"_{args.label}" if args.label else ""
        run_id = f"{datetime.now():%Y%m%d-%H%M}_{args.name}{suffix}"
        path = RESULTS / f"{run_id}.json"
        result = {"run_id": run_id, "記録日時": datetime.now().isoformat(timespec="seconds"), "区分": args.label,
                  **collect(args.name, args.minutes or f"{args.name}_議事録.md"), "人手版との比較": {k: None for k in MANUAL_KEYS}, "所見": []}
    if args.label:
        result["区分"] = args.label
    for kv in args.set:
        key, _, value = kv.partition("=")
        result["人手版との比較"][key.strip()] = float(value) if re.fullmatch(r"-?\d+(\.\d+)?", value.strip()) else value.strip()
    result["所見"] += args.note
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{result['run_id']} → {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
