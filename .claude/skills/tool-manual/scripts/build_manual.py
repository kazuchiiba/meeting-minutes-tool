"""docs 配下の md・JSON から、人が読むツール説明書（docs/ツール説明書.html）を1ファイルで作る。

md（設計書・詳細設計書・評価・Issue）は AI が読むもの、HTML は人が読むもの。
このスクリプトは md を変換して並べるだけで、Claude が中身を読む必要はない。
外部の CDN は使わない（社内情報を含むため、オフラインで開ける1ファイルにする）。

使い方（プロジェクトルートで、開発サイクルの最後に）:
    .venv/Scripts/python .claude/skills/tool-manual/scripts/build_manual.py
"""

import html
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[4]
DOCS = ROOT / "docs"
OUT = DOCS / "ツール説明書.html"
STATUS_ORDER = ["未着手", "検討中", "決定", "済", "保留"]
STATUS_LEGEND = {
    "未着手": "起票しただけ",
    "検討中": "選択肢を出して議論している",
    "決定": "方針は決まったが、対応が残っている",
    "済": "対応まで終わった",
    "保留": "今は決めない",
}


def md_to_html(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    # Issue の md へのリンクは、このページ内の該当箇所へのリンクに置き換える
    body = re.sub(r'href="[^"]*?(ISSUE-(\d+))[^"]*?\.md"', lambda m: f'href="#issue-{m.group(2)}"', body)
    return body


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def title_of(text: str, fallback: str) -> str:
    m = re.search(r"^# (.+)$", text, re.M)
    return m.group(1).strip() if m else fallback


def strip_h1(text: str) -> str:
    return re.sub(r"^# .+\n", "", text, count=1, flags=re.M)


def details(anchor: str, summary: str, inner: str, extra: str = "") -> str:
    return (f'<details id="{anchor}" class="doc"{extra}><summary>{html.escape(summary)}</summary>'
            f'<div class="doc-body">{inner}</div></details>')


def issues_section() -> tuple[str, Counter]:
    rows, docs = [], []
    files = sorted((DOCS / "issue" / "issue_md").glob("ISSUE-*.md"), key=lambda p: int(re.search(r"\d+", p.name).group()))
    for p in files:
        text = read(p)
        m = re.match(r"# (ISSUE-(\d+))\s+(.+)", text)
        field = lambda k: (re.search(rf"^\|\s*{k}\s*\|\s*(.*?)\s*\|\s*$", text, re.M) or [None, ""])[1]
        num, title, kind, status = m.group(2), m.group(3), field("区分"), field("状態")
        rows.append(f'<tr data-status="{status}"><td><a href="#issue-{num}">{m.group(1)}</a></td>'
                    f'<td>{html.escape(title)}</td><td>{kind}</td><td><span class="st st-{status}">{status}</span></td></tr>')
        docs.append(details(f"issue-{num}", f"{m.group(1)}　{title}（{status}）", md_to_html(strip_h1(text))))
    counts = Counter(re.search(r'data-status="([^"]*)"', r).group(1) for r in rows)
    legend = "".join(f'<li><span class="st st-{s}">{s}</span> {STATUS_LEGEND[s]}</li>' for s in STATUS_ORDER)
    buttons = "".join(f'<button data-filter="{s}">{s}（{counts.get(s, 0)}）</button>' for s in STATUS_ORDER)
    body = (f'<ul class="legend">{legend}</ul>'
            f'<div class="filters"><button data-filter="">すべて（{len(rows)}）</button>{buttons}</div>'
            f'<table class="issues"><thead><tr><th>ID</th><th>題名</th><th>区分</th><th>状態</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table><h3>Issue の内容</h3>{"".join(docs)}')
    return body, counts


def verification_section() -> str:
    results = sorted((json.loads(p.read_text(encoding="utf-8")) for p in (DOCS / "verification" / "results").glob("*.json")),
                     key=lambda r: r["run_id"])
    cols = [("run_id", lambda r: r["run_id"]), ("区分", lambda r: r.get("区分")),
            ("音声(分)", lambda r: r.get("会議", {}).get("音声の長さ_分")),
            ("処理時間合計(分)", lambda r: round(sum(v for v in r.get("処理時間_分", {}).values() if isinstance(v, (int, float))), 1)),
            ("文字数", lambda r: r.get("議事録", {}).get("文字数")),
            ("推定/不明/要確認", lambda r: "/".join(str(r.get("議事録", {}).get(k, "—")) for k in ("推定", "聞き取り不明", "要確認"))),
            ("抜けの候補", lambda r: r.get("自己点検", {}).get("抜けの候補")),
            ("無断推定", lambda r: r.get("人手版との比較", {}).get("無断推定")),
            ("話者誤り", lambda r: r.get("人手版との比較", {}).get("話者誤り")),
            ("人手版文字数", lambda r: r.get("人手版との比較", {}).get("人手版文字数"))]
    fmt = lambda v: "—" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else html.escape(str(v)))
    head = "".join(f"<th>{c}</th>" for c, _ in cols)
    body = "".join("<tr>" + "".join(f"<td>{fmt(f(r))}</td>" for _, f in cols) + "</tr>" for r in results)
    reports = "".join(details(f"report-{i}", r["run_id"], md_to_html(strip_h1(read(DOCS / "verification" / "reports" / f"{r['run_id']}.md"))))
                      for i, r in enumerate(results))
    others = "".join(details(f"verif-{i}", title_of(read(p), p.stem), md_to_html(strip_h1(read(p))))
                     for i, p in enumerate(sorted((DOCS / "verification").glob("*.md"))))
    return (f'<p>一覧の元データ：<code>docs/verification/results/*.json</code>（Excel：<code>docs/verification/テスト結果一覧.xlsx</code>）</p>'
            f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
            f'<h3>回ごとの報告</h3>{reports or "<p>（なし）</p>"}<h3>検証計画・比較資料</h3>{others}')


def design_detail_section() -> str:
    files = sorted((DOCS / "design" / "design_detail").glob("*.md"))
    if not files:
        return "<p>（詳細設計書はまだありません。開発サイクルの最後に design-detail スキルで作成します）</p>"
    return "".join(details(f"detail-{p.stem}", title_of(read(p), p.stem), md_to_html(strip_h1(read(p)))) for p in files)


CSS = """
:root{--bg:#fff;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--panel:#f6f8fa;--accent:#0969da;
--s-未着手:#fde9d9;--s-検討中:#fff2cc;--s-決定:#ddebf7;--s-済:#e2efda;--s-保留:#ededed}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--line:#3d444d;--panel:#151b23;--accent:#4493f8;
--s-未着手:#5a2e22;--s-検討中:#5a4a1a;--s-決定:#1e3a5a;--s-済:#22472a;--s-保留:#3a3a3a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.7 "Meiryo UI","Yu Gothic UI",system-ui,sans-serif}
nav{position:fixed;top:0;left:0;bottom:0;width:250px;overflow:auto;padding:20px 16px;border-right:1px solid var(--line);background:var(--panel)}
nav h1{font-size:16px;margin:0 0 4px}nav .gen{color:var(--muted);font-size:12px;margin-bottom:16px}
nav a{display:block;color:var(--fg);text-decoration:none;padding:4px 8px;border-radius:6px}nav a:hover{background:var(--line)}
main{margin-left:250px;padding:24px 40px 80px;max-width:1150px}
section{margin-bottom:48px}h2{border-bottom:2px solid var(--line);padding-bottom:6px;margin-top:8px}
table{border-collapse:collapse;margin:12px 0;font-size:14px}th,td{border:1px solid var(--line);padding:5px 9px;vertical-align:top;text-align:left}
th{background:var(--panel)}code{background:var(--panel);padding:1px 5px;border-radius:4px;font-size:13px}
pre{background:var(--panel);padding:12px;border-radius:6px;overflow:auto}pre code{padding:0}
a{color:var(--accent)}details.doc{border:1px solid var(--line);border-radius:8px;margin:8px 0;background:var(--bg)}
details.doc>summary{cursor:pointer;padding:8px 12px;font-weight:600}details.doc[open]>summary{border-bottom:1px solid var(--line);background:var(--panel)}
.doc-body{padding:4px 16px 12px}.scroll{overflow-x:auto}
.cards{display:flex;gap:12px;flex-wrap:wrap}.card{border:1px solid var(--line);border-radius:8px;padding:10px 16px;min-width:120px;background:var(--panel)}
.card b{display:block;font-size:22px}.st{padding:1px 8px;border-radius:10px;white-space:nowrap}
.st-未着手{background:var(--s-未着手)}.st-検討中{background:var(--s-検討中)}.st-決定{background:var(--s-決定)}.st-済{background:var(--s-済)}.st-保留{background:var(--s-保留)}
.legend{list-style:none;padding:0;display:flex;gap:16px;flex-wrap:wrap;font-size:13px}
.filters button{margin:0 6px 6px 0;padding:4px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--fg);cursor:pointer}
.filters button.on{border-color:var(--accent);color:var(--accent)}
@media (max-width:800px){nav{position:static;width:auto;border-right:0;border-bottom:1px solid var(--line)}main{margin-left:0;padding:16px}}
"""

JS = """
document.querySelectorAll('.filters button').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.filters button').forEach(x=>x.classList.toggle('on',x===b));
  const f=b.dataset.filter;document.querySelectorAll('table.issues tbody tr').forEach(r=>{r.style.display=!f||r.dataset.status===f?'':'none'});
}));
// ページ内リンクで閉じた details を開く
function openTarget(){const id=location.hash.slice(1);if(!id)return;const el=document.getElementById(id);if(el&&el.tagName==='DETAILS'){el.open=true;el.scrollIntoView();}}
window.addEventListener('hashchange',openTarget);openTarget();
"""


def main() -> None:
    design = read(DOCS / "design" / "議事録作成ツール設計書.md")
    issues_html, counts = issues_section()
    results = list((DOCS / "verification" / "results").glob("*.json"))
    details_count = len(list((DOCS / "design" / "design_detail").glob("*.md")))
    generated = f"{datetime.now():%Y/%m/%d %H:%M} 生成"
    cards = "".join(f'<div class="card">{k}<b>{v}</b></div>' for k, v in [
        ("Issue（全体）", sum(counts.values())), ("Issue（未完了）", sum(counts[s] for s in ("未着手", "検討中", "決定"))),
        ("テスト結果", len(results)), ("詳細設計書", details_count)])
    sections = [
        ("overview", "概要", f'<div class="cards">{cards}</div><p>このページは docs 配下の md・JSON から自動生成した、人が読むための説明書です。'
                             f'内容を直すときは元の md を直し、開発サイクルの最後に作り直します（手で編集しない）。</p>'),
        ("design", "設計書", md_to_html(strip_h1(design))),
        ("detail", "詳細設計書", design_detail_section()),
        ("verification", "評価（テスト結果）", verification_section()),
        ("issue", "Issue", issues_html),
    ]
    nav = "".join(f'<a href="#{a}">{t}</a>' for a, t, _ in sections)
    main_html = "".join(f'<section id="{a}"><h2>{t}</h2>{b}</section>' for a, t, b in sections)
    title = "議事録作成ツール 説明書"
    OUT.write_text(f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><nav><h1>{html.escape(title)}</h1><div class="gen">{generated}</div>{nav}</nav><main>{main_html}</main><script>{JS}</script></body></html>
""", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}（{OUT.stat().st_size // 1024} KB）")


if __name__ == "__main__":
    main()
