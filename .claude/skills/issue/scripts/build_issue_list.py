"""docs/issue/issue_md/ 配下の ISSUE-*.md から一覧を作り直す。

md ファイルが唯一の正本。一覧 (Excel と README の表) はこのスクリプトで生成するので手で編集しない。

使い方 (プロジェクトルートで):
    .venv/Scripts/python .claude/skills/issue/scripts/build_issue_list.py [issue_md フォルダ]
    （既定は docs/issue/issue_md。Excel はその1つ上のフォルダ docs/issue/ に出力する）

出力:
    docs/issue/Issue一覧.xlsx   ID・ファイル列から md を開けるハイパーリンク付き
    docs/issue/issue_md/README.md  <!-- ISSUE-LIST:START --> 〜 END の間の表を差し替え
"""

import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

FIELDS = ["区分", "状態", "起票日", "対象会議", "関連"]
STATUS_FILL = {
    "未着手": "FDE9D9",
    "検討中": "FFF2CC",
    "決定": "DDEBF7",
    "済": "E2EFDA",
    "保留": "EDEDED",
}
STATUS_LEGEND = "\n".join([  # 一覧の「状態」見出し（D1）に付けるコメント
    "状態の凡例",
    "未着手：起票しただけ",
    "検討中：選択肢を出して議論している",
    "決定：方針は決まったが、対応（実装・資料修正など）が残っている",
    "済：対応まで終わった。これ以上の作業はない",
    "保留：今は決めない（理由を記録）",
])
LIST_START = "<!-- ISSUE-LIST:START -->"
LIST_END = "<!-- ISSUE-LIST:END -->"


def section(text: str, heading_prefix: str) -> str:
    """'## 見出し' の本文を返す (次の '## ' まで)。"""
    m = re.search(rf"^## {re.escape(heading_prefix)}.*?$\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        return ""
    body = re.sub(r"^\s*（.*?）\s*$", "", m.group(1), flags=re.M)  # テンプレートの説明書きを除く
    return " ".join(line.strip() for line in body.splitlines() if line.strip())


def parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    h1 = re.search(r"^# (ISSUE-\d+)\s+(.+)$", text, re.M)
    row = {"ID": h1.group(1), "題名": h1.group(2).strip(), "file": path.name}
    for field in FIELDS:
        m = re.search(rf"^\|\s*{field}\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
        row[field] = m.group(1) if m else ""
    row["概要"] = section(text, "何が起きているか")
    row["決定内容"] = section(text, "決定内容")
    return row


def write_excel(rows: list[dict], out: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Issue一覧"
    headers = ["ID", "題名", "区分", "状態", "起票日", "対象会議", "概要", "決定内容", "関連", "ファイル"]
    widths = [12, 32, 8, 8, 11, 22, 60, 45, 28, 34]
    ws.append(headers)
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="305496")
        cell.alignment = Alignment(vertical="center")

    legend = Comment(STATUS_LEGEND, "Issue")
    legend.width, legend.height = 360, 130
    ws.cell(row=1, column=4).comment = legend

    link_font = Font(color="0563C1", underline="single")
    for r in rows:
        ws.append([r["ID"], r["題名"], r["区分"], r["状態"], r["起票日"], r["対象会議"],
                   r["概要"], r["決定内容"], r["関連"], r["file"]])
        i = ws.max_row
        for col in (1, 10):  # ID とファイル名から md を開ける (Excel ファイルからの相対パス)
            ws.cell(row=i, column=col).hyperlink = f"{r['dir']}/{r['file']}"  # Excel から見た相対パス
            ws.cell(row=i, column=col).font = link_font
        if r["状態"] in STATUS_FILL:
            ws.cell(row=i, column=4).fill = PatternFill("solid", fgColor=STATUS_FILL[r["状態"]])
        for col in range(1, len(headers) + 1):
            ws.cell(row=i, column=col).alignment = Alignment(wrap_text=True, vertical="top")

    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions

    # 区分 × 状態 の件数 (一覧シートを数式で集計するので、フィルタで行を足し引きしても追従する)
    summary = wb.create_sheet("集計")
    kinds = ["要件", "誤り", "論点", "不明点"]
    statuses = list(STATUS_FILL)
    summary.append(["区分 \\ 状態"] + statuses + ["合計"])
    n = max(ws.max_row, 2)
    for k in kinds:
        i = summary.max_row + 1
        summary.append([k] + [f'=COUNTIFS(Issue一覧!$C$2:$C${n},$A{i},Issue一覧!$D$2:$D${n},{get_column_letter(j + 2)}$1)'
                              for j in range(len(statuses))] + [f"=SUM(B{i}:{get_column_letter(len(statuses) + 1)}{i})"])
    i = summary.max_row + 1
    summary.append(["合計"] + [f"=SUM({get_column_letter(c)}2:{get_column_letter(c)}{i - 1})"
                               for c in range(2, len(statuses) + 3)])
    for cell in summary[1] + summary[summary.max_row]:
        cell.font = Font(bold=True)
    summary.column_dimensions["A"].width = 14

    wb.save(out)


def update_readme(rows: list[dict], readme: Path) -> None:
    table = ["| ID | 題名 | 区分 | 状態 |", "|---|---|---|---|"]
    table += [f"| [{r['ID']}]({r['file']}) | {r['題名']} | {r['区分']} | {r['状態']} |" for r in rows]
    block = f"{LIST_START}\n" + "\n".join(table) + f"\n{LIST_END}"
    text = readme.read_text(encoding="utf-8")
    if LIST_START in text:
        text = re.sub(rf"{re.escape(LIST_START)}.*?{re.escape(LIST_END)}", lambda _: block, text, flags=re.S)
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    readme.write_text(text, encoding="utf-8")


def main() -> None:
    issue_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/issue/issue_md")
    excel = issue_dir.parent / "Issue一覧.xlsx"
    files = sorted(issue_dir.glob("ISSUE-*.md"), key=lambda p: int(re.search(r"ISSUE-(\d+)", p.name).group(1)))
    rows = [parse(p) for p in files]
    for r in rows:
        r["dir"] = issue_dir.name
    write_excel(rows, excel)
    if (issue_dir / "README.md").exists():
        update_readme(rows, issue_dir / "README.md")
    for r in rows:
        print(f"{r['ID']}  [{r['状態']}] {r['区分']}  {r['題名']}")
    print(f"{len(rows)} 件 → {excel}")


if __name__ == "__main__":
    main()
