"""Teams・Notion などの文字起こしテキストの取り込みと、音声の文字起こしとの突き合わせ（docs/issue/issue_md/ISSUE-002）。

入力は3通り（run_pipeline.py が使い分ける）:
  1. 音声のみ           … このスクリプトは使わない
  2. テキストのみ       … import：テキストを読み込み、音声の文字起こしと同じ形式（.json / .txt / .speakers.txt）にする
  3. テキスト＋音声     … import の後、Whisper の文字起こしに align でテキストの話者名を時刻で付ける。
                           テキストは <名前>.text.txt として残し、議事録作成で本文を突き合わせる

対応するテキストの形式（自動判定）:
  .vtt         WebVTT（Teams）。「00:00:01.000 --> 00:00:05.000」の次の行に「<v 名前>本文</v>」
  .docx        Teams の文字起こし。「名前  0:03」の行の後に本文、または「0:0:0.0 --> 0:0:3.2」「名前」「本文」の順
  .txt / .md   Notion など。「[00:01:02] 名前: 本文」「名前: 本文」「名前 0:03」＋本文の行、または本文だけの行

使い方（プロジェクトルートで。通常は run_pipeline.py から呼ばれる）:
    .venv/Scripts/python src/import_text.py import <名前> <テキストファイル>
    .venv/Scripts/python src/import_text.py align <名前>

出力（transcripts/<名前>/）:
    <名前>.text.json      テキストを読み込んだ結果（時刻・話者・本文）
    <名前>.text.txt       同じものを読みやすくしたもの（議事録作成で Claude が読む）
    テキストのみの場合：<名前>.json / .txt / .speakers.txt / .meta.json
    テキスト＋音声の場合：<名前>.json と <名前>.speakers.txt に、テキストの話者名を付ける
"""

import argparse
import json
import re
from pathlib import Path

from merge_speakers import fmt_ts
from paths import transcript_stem

TIME = r"(\d{1,2}:\d{1,2}(?::\d{1,2})?(?:[.,]\d+)?)"


def to_sec(t: str) -> float:
    parts = [float(x) for x in t.replace(",", ".").split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_vtt(text: str) -> list[dict]:
    rows = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        m = re.search(rf"{TIME}\s*-->\s*{TIME}", block)
        if not m:
            continue
        body = block[m.end():].strip()
        speaker = ""
        v = re.search(r"<v\s+([^>]+)>", body)
        if v:
            speaker = v.group(1).strip()
        body = re.sub(r"<[^>]+>", "", body).strip()
        if not v and re.match(r"^([^:：\n]{1,20})[:：]", body):  # 「名前: 本文」形式の VTT
            speaker, body = [x.strip() for x in re.split(r"[:：]", body, maxsplit=1)]
        if body:
            rows.append({"start": to_sec(m.group(1)), "end": to_sec(m.group(2)), "speaker": speaker,
                         "text": " ".join(body.split())})
    return rows


def parse_lines(lines: list[str]) -> list[dict]:
    """docx の段落や txt / md の行を読む。"""
    rows, pending = [], None  # pending：見出し行（名前＋時刻）の後に本文が来る形式
    # Markdown の見出し（# …）は飛ばし、引用・箇条書きの記号を除く
    lines = [re.sub(r"^[>*\-\s]+", "", l).strip() for l in lines if not l.lstrip().startswith("#")]
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line:
            continue
        arrow = re.fullmatch(rf"{TIME}\s*-->\s*{TIME}", line)
        if arrow:  # 旧形式の Teams docx：時刻 → 名前 → 本文
            speaker = lines[i] if i < len(lines) else ""
            body = lines[i + 1] if i + 1 < len(lines) else ""
            i += 2
            rows.append({"start": to_sec(arrow.group(1)), "end": to_sec(arrow.group(2)), "speaker": speaker, "text": body})
            continue
        m = re.fullmatch(rf"\[?{TIME}\]?\s*([^:：]{{1,20}})[:：]\s*(.+)", line)  # [時刻] 名前: 本文
        if m:
            rows.append({"start": to_sec(m.group(1)), "end": None, "speaker": m.group(2).strip(), "text": m.group(3).strip()})
            continue
        m = re.fullmatch(rf"(.{{1,20}}?)\s+{TIME}", line)  # 名前  時刻（次の行から本文）
        if m:
            pending = {"start": to_sec(m.group(2)), "end": None, "speaker": m.group(1).strip(), "text": ""}
            rows.append(pending)
            continue
        m = re.fullmatch(r"([^:：\s]{1,20})[:：]\s*(.+)", line)  # 名前: 本文
        if m:
            pending = None
            rows.append({"start": None, "end": None, "speaker": m.group(1), "text": m.group(2).strip()})
            continue
        if pending is not None:  # 見出し行に続く本文
            pending["text"] = (pending["text"] + " " + line).strip()
        else:
            rows.append({"start": None, "end": None, "speaker": "", "text": line})
    return [r for r in rows if r["text"]]


def parse(path: Path) -> tuple[list[dict], str]:
    suffix = path.suffix.lower()
    if suffix == ".vtt":
        return parse_vtt(path.read_text(encoding="utf-8-sig")), "WebVTT"
    if suffix == ".docx":
        import docx

        return parse_lines([p.text for p in docx.Document(str(path)).paragraphs]), "Word（Teams の文字起こしなど）"
    text = path.read_text(encoding="utf-8-sig")
    if "-->" in text and re.search(rf"^{TIME}\s*-->", text, re.M):
        return parse_vtt(text), "WebVTT 形式のテキスト"
    return parse_lines(text.splitlines()), "テキスト（Notion など）"


def fill_end(rows: list[dict]) -> None:
    """終了時刻がない行は、次の行の開始時刻を終了時刻とする。"""
    for a, b in zip(rows, rows[1:] + [None]):
        if a["start"] is not None and a["end"] is None:
            a["end"] = b["start"] if b and b["start"] is not None else a["start"] + 30


def readable(rows: list[dict]) -> str:
    out = []
    for r in rows:
        ts = f"[{fmt_ts(r['start'])}] " if r["start"] is not None else ""
        out.append(f"{ts}{r['speaker'] + ': ' if r['speaker'] else ''}{r['text']}")
    return "\n".join(out) + "\n"


def cmd_import(name: str, text_file: Path, text_only: bool) -> None:
    stem = transcript_stem(name)
    rows, fmt = parse(text_file)
    fill_end(rows)
    Path(f"{stem}.text.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(f"{stem}.text.txt").write_text(readable(rows), encoding="utf-8")
    speakers = sorted({r["speaker"] for r in rows if r["speaker"]})
    timed = sum(1 for r in rows if r["start"] is not None)
    print(f"テキストを取り込みました：{text_file.name}（{fmt}、{len(rows)} 行、時刻付き {timed} 行、話者 {len(speakers)} 名：{'、'.join(speakers)}）")

    if text_only:  # 音声の文字起こしと同じ形式のファイルを作る（以降の工程をそのまま使えるように）
        segs = [{"id": i, "start": r["start"] or 0.0, "end": r["end"] or 0.0, "text": r["text"],
                 "speaker": r["speaker"] or "不明"} for i, r in enumerate(rows, 1)]
        stem.with_suffix(".json").write_text(json.dumps(segs, ensure_ascii=False, indent=1), encoding="utf-8")
        stem.with_suffix(".txt").write_text(readable([{**r, "speaker": ""} for r in rows]), encoding="utf-8")
        Path(f"{stem}.speakers.txt").write_text(readable(rows), encoding="utf-8")
        Path(f"{stem}.meta.json").write_text(json.dumps({
            "source": "テキストのみ", "text_file": text_file.name, "format": fmt, "segments": len(rows),
            "speakers_in_text": speakers, "note": "音声なし。話者はテキストの記載に従う。",
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"speakers": speakers}, ensure_ascii=False))


def cmd_align(name: str) -> None:
    """Whisper のセグメントに、時刻が最も重なるテキストの行の話者名を付ける。"""
    stem = transcript_stem(name)
    rows = json.loads(Path(f"{stem}.text.json").read_text(encoding="utf-8"))
    timed = [r for r in rows if r["start"] is not None and r["speaker"]]
    segs = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
    matched = 0
    for seg in segs:
        best, best_overlap = None, 0.0
        for r in timed:
            o = min(seg["end"], r["end"]) - max(seg["start"], r["start"])
            if o > best_overlap:
                best, best_overlap = r, o
        seg["speaker"] = best["speaker"] if best else "不明"
        matched += best is not None
    stem.with_suffix(".json").write_text(json.dumps(segs, ensure_ascii=False, indent=1), encoding="utf-8")

    lines, cur = [], None  # 同じ話者が続く間は1行にまとめる
    for seg in segs:
        if cur and cur["speaker"] == seg["speaker"]:
            cur["text"] += " " + seg["text"]
        else:
            cur = {"start": seg["start"], "speaker": seg["speaker"], "text": seg["text"]}
            lines.append(cur)
    Path(f"{stem}.speakers.txt").write_text(
        "\n".join(f"[{fmt_ts(l['start'])}] {l['speaker']}: {l['text']}" for l in lines) + "\n", encoding="utf-8")

    meta_path = Path(f"{stem}.meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["text_alignment"] = {
        "source": "テキスト＋音声", "timed_text_rows": len(timed), "segments": len(segs), "matched_segments": matched,
        "note": "本文は Whisper、話者はテキスト（時刻の重なりで対応付け）。テキストの本文は <名前>.text.txt。",
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if not timed:
        print("テキストに時刻がないため、話者を時刻で対応付けられませんでした（議事録作成で Claude が .text.txt と突き合わせる）")
    print(f"話者を付けました：{matched}/{len(segs)} セグメント")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("import")
    i.add_argument("name")
    i.add_argument("text_file", type=Path)
    i.add_argument("--text-only", action="store_true", help="音声がない場合（以降の工程用のファイルも作る）")
    a = sub.add_parser("align")
    a.add_argument("name")
    args = parser.parse_args()
    if args.cmd == "import":
        cmd_import(args.name, args.text_file, args.text_only)
    else:
        cmd_align(args.name)


if __name__ == "__main__":
    main()
