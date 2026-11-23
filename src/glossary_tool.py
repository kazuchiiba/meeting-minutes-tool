"""用語集（docs/design/議事録作成用の用語集.xlsx）の読み出しと、追加候補の抽出。

使い方:
    # 議事録作成（④）の前に、Claude が読む形で用語集を書き出す
    .venv/Scripts/python src/glossary_tool.py dump

    # Word 出力（⑥）の後に、用語集への追加候補を抽出して「候補」シートに追記する（⑦）
    .venv/Scripts/python src/glossary_tool.py candidates transcripts/<名前>/<名前>.json output_MeetingMinutes/<名前>/evidence_log/<名前>_議事録.md

    # 候補を見て、Claude が登録先のおすすめ（用語 / 人名 / 不要 と理由）を「Claudeの推奨」列に書く
    .venv/Scripts/python src/glossary_tool.py recommend <おすすめの JSON>

追加候補の種類:
    推定        議事録で【推定：「元の語」】とした語（文字起こしの誤変換と、Claude が推定した正式表記の組）
    聞き取り不明  議事録で【聞き取り不明：「元の語」】とした語（正式表記を人に確認したい）
    人名        議事録で 氏名【要確認：人名】 とした、名簿にない人名
    頻出語      文字起こしに3回以上出るカタカナ・英字の語で、用語集にないもの
候補は「候補」シートに「未確認」で追記する。記録者が確認し、登録先（用語 / 人名 / 不要）を選ぶ。
"""

import argparse
import json
import os
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
GLOSSARY = Path(os.environ.get("GLOSSARY_PATH", ROOT / "docs" / "design" / "議事録作成用の用語集.xlsx"))  # テスト時は環境変数で差し替え
CANDIDATE_SHEET = "候補"
RECOMMEND_HEADER = "Claudeの推奨"
CANDIDATE_HEADER = ["No.", "種類", "文字起こしでの表記", "推定した表記", "議事録の該当箇所", "出典", "抽出日",
                    "登録先", "正式表記（確認後）", "意味", "確認", "修正・コメント"]
FREQUENT_MIN = 3
COMMON = {"ありがとうございます", "ございます", "スケジュール", "データ", "システム", "ツール", "メール", "チーム", "メーカー",
          "マネージャー", "リスト", "ルール", "フロー", "パターン", "イメージ", "スタート", "チェック", "エクセル", "ファイル",
          "グループ", "コード", "トラブル", "タイミング", "センター", "アレンジ", "OK", "ケース", "フォーマット", "ベース",
          "プロジェクト", "コメント", "メンバー", "サービス", "ポイント", "レベル", "テーマ", "メイン", "オーケー"}


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", str(s or "")).casefold()


def known_terms(wb) -> set[str]:
    known = set()
    for sheet in ("用語", "人名", CANDIDATE_SHEET):
        if sheet not in wb.sheetnames:
            continue
        for row in wb[sheet].iter_rows(min_row=2, values_only=True):
            for cell in row[1:4]:
                for t in re.split(r"[/、,\n]", re.sub(r"（.*?）|\(.*?\)", "", str(cell or ""))):
                    if t.strip() and t.strip() not in ("—", "-", "None"):
                        known.add(norm(t.strip()))
    return known


def dump() -> None:
    wb = load_workbook(GLOSSARY, read_only=True)
    for sheet in ("用語", "人名"):
        print(f"## {sheet}（正式表記 | 意味・所属 | 文字起こしでの誤変換例）")
        for row in wb[sheet].iter_rows(min_row=2, values_only=True):
            if row[1]:
                clean = lambda v: re.sub(r"\s+", " ", str(v or "—")).strip()
                print(f"- {clean(row[1])} | {clean(row[2])} | {clean(row[3])}")
        print()


def candidates(transcript: Path, minutes: Path) -> None:
    wb = load_workbook(GLOSSARY)
    known = known_terms(wb)
    md = minutes.read_text(encoding="utf-8")
    found: list[dict] = []

    for m in re.finditer(r"([^\s【】、。（）()「」]{0,15})【(推定|聞き取り不明)(?:：([^】]*))?】", md):
        before, kind, note = m.group(1), m.group(2), m.group(3) or ""
        originals = re.findall(r"「([^」]+)」", note)  # 文字起こしの元の語は「」で囲んで書くルール
        word = re.search(r"[A-Za-z0-9゠-ヿー一-鿿々]+(?:さん)?$", before)
        guess = word.group(0) if word else before[-8:]
        for orig in originals:
            if len(orig) > 25 or norm(orig) in known:
                continue
            line = md[md.rfind("\n", 0, m.start()) + 1 : md.find("\n", m.end())]
            found.append({"種類": kind, "文字起こしでの表記": orig, "推定した表記": guess if kind == "推定" else "",
                          "議事録の該当箇所": line.strip()[:100]})

    # 名簿にない人名（作成ルール12：氏名【要確認：人名】）
    # 漢字・カタカナの名前、または「としさん」のようなひらがなの名前（さんの前）
    for m in re.finditer(r"([一-鿿々ァ-ヺー]{1,6}|(?<![ぁ-ゖ])[ぁ-ゖ]{2,4}(?=さん))(?:さん)?【要確認：人名】", md):
        if norm(m.group(1)) not in known:
            line = md[md.rfind("\n", 0, m.start()) + 1 : md.find("\n", m.end())]
            found.append({"種類": "人名", "文字起こしでの表記": m.group(1), "推定した表記": "",
                          "議事録の該当箇所": line.strip()[:100]})

    segments = json.loads(transcript.read_text(encoding="utf-8"))
    counts = Counter(t for s in segments for t in re.findall(r"[A-Za-z]?[゠-ヿー]{3,}|[A-Za-z][A-Za-z0-9]{1,}", s["text"]))
    for term, n in counts.most_common():
        if n < FREQUENT_MIN:
            break
        if term in COMMON or any(norm(term) in k for k in known if len(k) >= len(term)):
            continue
        found.append({"種類": "頻出語", "文字起こしでの表記": term, "推定した表記": "", "議事録の該当箇所": f"文字起こしに {n} 回"})

    unique = {}
    for f in found:
        unique.setdefault((f["種類"], f["文字起こしでの表記"]), f)

    ws = wb[CANDIDATE_SHEET] if CANDIDATE_SHEET in wb.sheetnames else None
    if ws is None:
        ws = wb.create_sheet(CANDIDATE_SHEET, index=2)
        ws.append(CANDIDATE_HEADER)
        for c, w in enumerate([5, 10, 22, 18, 50, 40, 11, 10, 20, 30, 9, 30, 40], 1):
            cell = ws.cell(row=1, column=c)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="305496")
            ws.column_dimensions[cell.column_letter].width = w
        for col, values in (("H", '"用語,人名,不要"'), ("K", '"未確認,確認済"')):
            dv = DataValidation(type="list", formula1=values)
            ws.add_data_validation(dv)
            dv.add(f"{col}2:{col}1000")
        ws.freeze_panes = "C2"
    ensure_recommend_column(ws)
    start = ws.max_row
    source = f"{minutes.relative_to(ROOT).as_posix()}\n{transcript.relative_to(ROOT).as_posix()}"
    for i, f in enumerate(unique.values(), start=start):
        ws.append([i, f["種類"], f["文字起こしでの表記"], f["推定した表記"], f["議事録の該当箇所"], source,
                   date.today().isoformat(), "", "", "", "未確認", ""])
        for cell in ws[ws.max_row]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.auto_filter.ref = ws.dimensions
    wb.save(GLOSSARY)

    print(f"用語集の追加候補：{len(unique)} 件（「{CANDIDATE_SHEET}」シートの No.{start}〜 に追記）")
    print("→ Claude が各候補の登録先のおすすめを recommend で「Claudeの推奨」列に書き、おすすめを記録者に伝える")
    for kind in ("推定", "聞き取り不明", "人名", "頻出語"):
        items = [f["文字起こしでの表記"] + (f"→{f['推定した表記']}" if f["推定した表記"] else "")
                 for f in unique.values() if f["種類"] == kind]
        if items:
            print(f"- {kind}（{len(items)}）：{'、'.join(items[:30])}{' …' if len(items) > 30 else ''}")


def ensure_recommend_column(ws) -> int:
    """「Claudeの推奨」列（13列目）がなければ見出しを付ける。列番号を返す。"""
    col = len(CANDIDATE_HEADER) + 1
    if ws.cell(row=1, column=col).value != RECOMMEND_HEADER:
        cell = ws.cell(row=1, column=col, value=RECOMMEND_HEADER)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="305496")
        ws.column_dimensions[cell.column_letter].width = 40
    return col


def recommend(path: Path) -> None:
    """Claude が判断した登録先のおすすめ（{No.: "用語：理由" など}の JSON）を「Claudeの推奨」列に書く。"""
    advice = {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    wb = load_workbook(GLOSSARY)
    ws = wb[CANDIDATE_SHEET]
    col = ensure_recommend_column(ws)
    done = 0
    for row in ws.iter_rows(min_row=2):
        if row[0].value in advice:
            cell = ws.cell(row=row[0].row, column=col, value=advice[row[0].value])
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            done += 1
    ws.auto_filter.ref = ws.dimensions
    wb.save(GLOSSARY)
    print(f"「Claudeの推奨」を {done} 件書きました")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dump")
    c = sub.add_parser("candidates")
    c.add_argument("transcript", type=Path)
    c.add_argument("minutes", type=Path)
    r = sub.add_parser("recommend")
    r.add_argument("advice", type=Path, help='{"No.": "用語：理由"} の JSON')
    args = parser.parse_args()
    if args.cmd == "dump":
        dump()
    elif args.cmd == "recommend":
        recommend(args.advice)
    else:
        candidates(args.transcript.resolve(), args.minutes.resolve())


if __name__ == "__main__":
    main()
