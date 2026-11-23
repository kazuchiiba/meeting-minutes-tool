"""議事録の自己点検（docs/issue/issue_md/ISSUE-014・015）。

1. 抜けの点検：文字起こしの各セグメントの「内容語」（漢字・カタカナ・英数字の語、数字）が
   議事録にどれだけ含まれるかを調べ、含まれる割合が低いセグメントを一覧にする。
2. 根拠のない語の点検：議事録にあるカタカナ・英数字の語のうち、文字起こしにも用語集にもないものを一覧にする
   （印を付けずに別の語へ言い換えた可能性がある箇所）。

文字起こしの誤変換は、用語集の「文字起こしでの誤変換例」→「正式表記」で置き換えてから照合する。
一覧は機械的な候補なので、最後は Claude または人が文字起こしと議事録を見て判断する。

使い方:
    .venv/Scripts/python src/check_coverage.py transcripts/<名前>/<名前>.json output_MeetingMinutes/<名前>/evidence_log/<名前>_議事録.md
出力（議事録 md と同じフォルダ＝evidence_log/）:
    <名前>_議事録.check.md    候補の一覧（Claude・人が読む）
    <名前>_議事録.check.json  件数（テスト結果の記録に使う）
"""

import argparse
import json
import re
import unicodedata
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
GLOSSARY = ROOT / "docs" / "design" / "議事録作成用の用語集.xlsx"

COVERAGE_THRESHOLD = 0.5  # 内容語のうち議事録に含まれる割合がこれ未満なら「抜けの候補」
MIN_TOKENS = 2  # 内容語がこれより少ないセグメント（相づちなど）は対象外

TOKEN = re.compile(
    r"[一-鿿々]{2,}"  # 漢字2字以上
    r"|[ァ-ヺー]{2,}"  # カタカナ2字以上（中黒「・」は語の区切りとして扱う）
    r"|[A-Za-z][A-Za-z0-9.\-]*"  # 英字で始まる語
    r"|\d[\d,.]*"  # 数字
)
PROPER = re.compile(r"[ァ-ヺー]{3,}|[A-Za-z][A-Za-z0-9.\-]{1,}")  # 言い換えの点検対象（固有名詞になりやすい語）
STOP = {"です", "ます", "ちょっと", "ところ", "ような", "みたい", "という", "って", "ので", "けど", "でも", "あと", "はい"}


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def load_glossary() -> tuple[list[tuple[str, str]], set[str]]:
    """(誤変換例, 正式表記) の置換表と、正式表記の集合。"""
    pairs, official = [], set()
    if not GLOSSARY.exists():
        return pairs, official
    wb = load_workbook(GLOSSARY, read_only=True)
    for sheet in ("用語", "人名"):
        for row in wb[sheet].iter_rows(min_row=2, values_only=True):
            if not row[1]:
                continue
            names = [n.strip() for n in re.split(r"[/、]", re.sub(r"（.*?）|\(.*?\)", "", str(row[1]))) if n.strip()]
            official.update(norm(n) for n in names)
            for mis in re.split(r"[、,]", re.sub(r"（.*?）|\(.*?\)", "", str(row[3] or ""))):
                mis = mis.strip()
                if mis and mis not in ("—", "-") and names and norm(mis) != norm(names[0]):
                    pairs.append((mis, names[0]))
    pairs.sort(key=lambda p: -len(p[0]))  # 長い誤変換例から置き換える
    return pairs, official


def correct(text: str, pairs: list[tuple[str, str]]) -> str:
    for mis, right in pairs:
        text = text.replace(mis, right)
    return text


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(norm(text)) if t not in STOP]


def contained(token: str, body: str) -> bool:
    if token in body:
        return True
    if re.fullmatch(r"[一-鿿々]{3,}", token):  # 長い漢字語は2字ずつの半分以上が含まれればよしとする
        grams = [token[i : i + 2] for i in range(len(token) - 1)]
        return sum(g in body for g in grams) >= len(grams) / 2
    return False


def fmt_ts(sec: float) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02}:{m:02}:{s:02}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path, help="transcripts/<名前>/<名前>.json")
    parser.add_argument("minutes", type=Path, help="output_MeetingMinutes/<名前>/evidence_log/<名前>_議事録.md")
    args = parser.parse_args()

    pairs, official = load_glossary()
    segments = json.loads(args.transcript.read_text(encoding="utf-8"))
    minutes_text = args.minutes.read_text(encoding="utf-8")
    body = norm(re.sub(r"^>.*$", "", minutes_text, flags=re.M))  # 末尾の注記は除く

    # 1. 抜けの点検
    gaps = []
    for seg in segments:
        toks = list(dict.fromkeys(tokens(correct(seg["text"], pairs))))
        if len(toks) < MIN_TOKENS:
            continue
        missing = [t for t in toks if not contained(t, body)]
        ratio = 1 - len(missing) / len(toks)
        if ratio < COVERAGE_THRESHOLD:
            gaps.append((seg, ratio, missing))

    # 2. 根拠のない語の点検
    raw_all = norm(" ".join(s["text"] for s in segments))
    transcript_all = norm(correct(" ".join(s["text"] for s in segments), pairs))
    unsupported = {}
    flagged = re.sub(r"[A-Za-z0-9ァ-ヺー一-鿿々]+【推定[^】]*】", " ", minutes_text)  # 印付きで推定した語は対象外
    flagged = re.sub(r"^(>|※記).*$", "", flagged, flags=re.M)  # 末尾の注記と「※記」（記録者・AI の注記）は対象外
    for line in re.sub(r"【[^】]*】", " ", flagged).splitlines():
        for t in PROPER.findall(norm(line)):
            if t in raw_all or t in transcript_all or t in official or any(t in o or o in t for o in official if len(o) >= 3):
                continue
            unsupported.setdefault(t, line.strip()[:80])

    out = args.minutes.with_suffix(".check.md")
    lines = [
        f"# 自己点検：{args.minutes.name}",
        "",
        f"- 文字起こし：`{args.transcript}`（{len(segments)} セグメント）",
        f"- 抜けの候補：{len(gaps)} 件（内容語の含有率 {COVERAGE_THRESHOLD:.0%} 未満）",
        f"- 根拠のない語の候補：{len(unsupported)} 件",
        "- いずれも機械的な候補。文字起こしと議事録を見て、本当に抜け・言い換えかを判断する。",
        "",
        "## 1. 抜けの候補",
        "",
        "| 時刻 | 話者 | 含有率 | 文字起こし | 議事録にない内容語 |",
        "|---|---|---|---|---|",
    ]
    for seg, ratio, missing in gaps:
        text = seg["text"].replace("|", "｜")
        lines.append(f"| {fmt_ts(seg['start'])} | {seg.get('speaker', '')} | {ratio:.0%} | {text} | {'、'.join(missing)} |")
    lines += ["", "## 2. 根拠のない語の候補", "", "| 語 | 議事録の該当行 |", "|---|---|"]
    lines += [f"| {t} | {ctx.replace('|', '｜')} |" for t, ctx in unsupported.items()]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args.minutes.with_suffix(".check.json").write_text(json.dumps({
        "segments": len(segments),
        "gap_candidates": len(gaps),
        "unsupported_candidates": len(unsupported),
        "threshold": COVERAGE_THRESHOLD,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{out}: 抜けの候補 {len(gaps)} 件 / 根拠のない語の候補 {len(unsupported)} 件")


if __name__ == "__main__":
    main()
