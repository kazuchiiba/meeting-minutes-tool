"""docs/verification/results/*.json から、テスト結果一覧（Excel）と回ごとの報告（md）を作り直す。

JSON が正本。Excel と md はこのスクリプトで生成するので手で編集しない。

使い方（プロジェクトルートで）:
    .venv/Scripts/python .claude/skills/verification/scripts/build_report.py

出力:
    docs/verification/テスト結果一覧.xlsx   人が見る一覧（run_id から報告 md を開ける）
    docs/verification/reports/<run_id>.md  回ごとの報告（AI が読む。HTML のツール説明書にも取り込まれる）
"""

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[4]
VERIFY = ROOT / "docs" / "verification"
RESULTS = VERIFY / "results"
REPORTS = VERIFY / "reports"

COLUMNS = [  # (見出し, JSON 上の場所)
    ("run_id", ("run_id",)),
    ("区分", ("区分",)),
    ("会議", ("会議", "名前")),
    ("種類", ("会議", "会議の種類")),
    ("音声(分)", ("会議", "音声の長さ_分")),
    ("①文字起こし(分)", ("処理時間_分", "① 文字起こし")),
    ("②話者分離(分)", ("処理時間_分", "② 話者分離")),
    ("③補完(分)", ("処理時間_分", "③ 抜けの補完")),
    ("④作成(分)", ("処理時間_分", "④ 議事録の作成")),
    ("⑤点検(分)", ("処理時間_分", "⑤ 自己点検")),
    ("文字数", ("議事録", "文字数")),
    ("段落数", ("議事録", "段落数")),
    ("見出し数", ("議事録", "見出し数")),
    ("推定", ("議事録", "推定")),
    ("聞き取り不明", ("議事録", "聞き取り不明")),
    ("要確認", ("議事録", "要確認")),
    ("抜けの候補", ("自己点検", "抜けの候補")),
    ("根拠のない語", ("自己点検", "根拠のない語の候補")),
    ("用語集候補", ("用語集の追加候補",)),
    ("付け足し", ("人手版との比較", "付け足し")),
    ("確度の格上げ", ("人手版との比較", "確度の格上げ")),
    ("無断推定", ("人手版との比較", "無断推定")),
    ("話者誤り", ("人手版との比較", "話者誤り")),
    ("網羅数", ("人手版との比較", "網羅数")),
    ("キーポイント数", ("人手版との比較", "キーポイント数")),
]


def get(d: dict, path: tuple):
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def fmt(v) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def write_report(r: dict) -> None:
    lines = [f"# テスト結果 {r['run_id']}", "",
             f"- 区分：{fmt(r.get('区分'))}", f"- 記録日時：{r.get('記録日時', '')}", ""]
    sections = [("会議", r.get("会議", {})), ("処理時間（分）", r.get("処理時間_分", {})),
                ("文字起こし", r.get("文字起こし", {})), ("議事録", r.get("議事録", {})),
                ("自己点検", r.get("自己点検", {})), ("人手版との比較", r.get("人手版との比較", {}))]
    for title, data in sections:
        lines += [f"## {title}", "", "| 項目 | 値 |", "|---|---|"]
        lines += [f"| {k} | {fmt(v)} |" for k, v in data.items()]
        if title == "処理時間（分）" and data:
            lines.append(f"| 合計 | {sum(v for v in data.values() if isinstance(v, (int, float))):.1f} |")
        lines.append("")
    lines += ["## 用語集の追加候補", "", f"{fmt(r.get('用語集の追加候補'))} 件", "", "## 所見", ""]
    lines += [f"- {n}" for n in r.get("所見", [])] or ["- （なし）"]
    (REPORTS / f"{r['run_id']}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_excel(results: list[dict]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "テスト結果一覧"
    ws.append([c for c, _ in COLUMNS] + ["所見"])
    for i, cell in enumerate(ws[1], 1):
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="305496")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = 30 if i == 1 else (60 if i == len(COLUMNS) + 1 else 10)
    for r in results:
        ws.append([get(r, p) for _, p in COLUMNS] + ["\n".join(r.get("所見", []))])
        row = ws.max_row
        ws.cell(row=row, column=1).hyperlink = f"reports/{r['run_id']}.md"
        ws.cell(row=row, column=1).font = Font(color="0563C1", underline="single")
        for cell in ws[row]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions
    out = VERIFY / "テスト結果一覧.xlsx"
    wb.save(out)
    return out


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    results = sorted((json.loads(p.read_text(encoding="utf-8")) for p in RESULTS.glob("*.json")),
                     key=lambda r: r["run_id"])
    for r in results:
        write_report(r)
    out = write_excel(results)
    for r in results:
        print(f"{r['run_id']:<45} {fmt(r.get('区分')):<6} 文字数 {fmt(get(r, ('議事録', '文字数'))):>6}  "
              f"抜けの候補 {fmt(get(r, ('自己点検', '抜けの候補'))):>3}  話者誤り {fmt(get(r, ('人手版との比較', '話者誤り')))}")
    print(f"{len(results)} 件 → {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
