"""詳細設計書（docs/design/design_detail/*.md）が、元のコードと合っているかを調べる。

各詳細設計書の1行目に `<!-- source: src/xxx.py sha: 0123456789ab -->` を入れておき、
コードのハッシュと比べて「未作成 / 要更新 / 最新」を判定する。書き直すのは「未作成」「要更新」だけでよい。

使い方（プロジェクトルートで）:
    .venv/Scripts/python .claude/skills/design-detail/scripts/stale.py          # 一覧
    .venv/Scripts/python .claude/skills/design-detail/scripts/stale.py --header src/xxx.py   # 1行目に入れる行を表示
"""

import argparse
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TARGETS = ["src/*.py"]  # 詳細設計書を作る対象
DETAIL = ROOT / "docs" / "design" / "design_detail"
HEADER = re.compile(r"<!-- source: (\S+) sha: ([0-9a-f]+) -->")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def header_line(src: Path) -> str:
    return f"<!-- source: {src.relative_to(ROOT).as_posix()} sha: {sha(src)} -->"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--header", type=Path, help="詳細設計書の1行目に入れる行を表示する")
    args = parser.parse_args()
    if args.header:
        print(header_line((ROOT / args.header).resolve()))
        return

    sources = sorted(p for pattern in TARGETS for p in ROOT.glob(pattern))
    docs = {p.stem: p for p in DETAIL.glob("*.md")}
    rows = []
    for src in sources:
        doc = docs.pop(src.stem, None)
        if doc is None:
            status = "未作成"
        else:
            m = HEADER.search(doc.read_text(encoding="utf-8").splitlines()[0] if doc.stat().st_size else "")
            status = "最新" if m and m.group(2) == sha(src) else "要更新"
        rows.append((status, src.relative_to(ROOT).as_posix()))
    rows += [("元のコードなし", f"docs/design/design_detail/{d.name}") for d in docs.values()]

    for status, path in rows:
        print(f"{status:<8} {path}")
    todo = [p for s, p in rows if s in ("未作成", "要更新")]
    print(f"\n書き直しが必要：{len(todo)} 件 / 全 {len(rows)} 件")


if __name__ == "__main__":
    main()
