"""GitHub に上げる公開用コピーを作る（private リポジトリ meeting-minutes-tool 用）。

手元のファイルは変えない。publish/meeting-minutes-tool/ に、上げないものを除いてコピーし、
private/公開用の置き換え表.tsv の語（実名・社名・部署名）を置き換える。最後に置き換え漏れを検査する。

使い方（プロジェクトルートで）:
    .venv/Scripts/python tools/export_public.py           コピーを作り直して検査する
    .venv/Scripts/python tools/export_public.py --check   検査だけ行う

- 置き換えは、文章・ファイル名・フォルダ名・Excel のセルとリンク先・Word の本文（XML）・作成者情報に行う。
- 前回のコピーにあって今回は作られないファイルは、消さずに publish/_stale/<日時>/ へ移す（ファイルは削除しない）。
- 置き換え表は実名の一覧なので、GitHub には上げない（.gitignore の private/）。
"""

import argparse
import os
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from paths import move_into  # noqa: E402

DEST = ROOT / "publish" / "meeting-minutes-tool"
STALE = ROOT / "publish" / "_stale"
TABLE = ROOT / "private" / "公開用の置き換え表.tsv"

# 上げないもの（プロジェクトルートからの相対パスの先頭、またはファイル名のパターン）
EXCLUDE_DIRS = {"input", "output_MeetingMinutes", "transcripts", "logs", "private", "publish",
                ".venv", ".venv-diar", "__pycache__", ".git"}
EXCLUDE_FILES = [r"^~\$", r"\.pyc$", r"\.log$", r"\.(m4a|mp3|wav|mp4|aac|flac|ogg|webm|mov)$",
                 r"^議事録作成用の用語集\.xlsx$", r"^settings\.local\.json$"]
TEXT_EXT = {".md", ".py", ".json", ".html", ".lean", ".txt", ".yaml", ".yml", ".toml", ".csv", ".tsv",
            ".js", ".css", ".ps1", ".sh", ".gitignore", ".xml", ".svg"}

BOUNDARY = {"plain": ("", ""),
            "kanji1": (r"(?<![一-龥々])", r"(?![一-龥々])"),
            "kana": (r"(?<![ァ-ヶー])", r"(?![ァ-ヶー])"),
            "ascii": (r"(?<![A-Za-z])", r"(?![A-Za-z])")}


def load_table() -> list[tuple[re.Pattern, str, str]]:
    rows = []
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        word, repl, kind = line.split("\t")
        before, after = BOUNDARY[kind]
        rows.append((re.compile(before + re.escape(word) + after), repl, word))
    return sorted(rows, key=lambda r: -len(r[2]))  # 長い語から（「A」を「J」より先に）


def anonymize(text: str, table) -> str:
    for pattern, repl, _ in table:
        text = pattern.sub(repl, text)
    return text


def excluded(rel: Path) -> bool:
    if rel.parts[0] in EXCLUDE_DIRS or any(p in EXCLUDE_DIRS for p in rel.parts):
        return True
    return any(re.search(p, rel.name) for p in EXCLUDE_FILES)


def copy_xlsx(src: Path, dst: Path, table) -> None:
    from openpyxl import load_workbook

    wb = load_workbook(src)
    for ws in wb.worksheets:
        ws.title = anonymize(ws.title, table)
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str):
                    c.value = anonymize(c.value, table)
                if c.hyperlink is not None and c.hyperlink.target:
                    c.hyperlink.target = anonymize(c.hyperlink.target, table)
    wb.properties.creator = wb.properties.lastModifiedBy = ""
    wb.save(dst)


def copy_zip_xml(src: Path, dst: Path, table) -> None:
    """docx など：中の XML の文字を置き換え、作成者情報を消す。"""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith((".xml", ".rels")):
                s = anonymize(data.decode("utf-8"), table)
                if item.filename == "docProps/core.xml":
                    s = re.sub(r"<(dc:creator|cp:lastModifiedBy)>.*?</\1>", r"<\1></\1>", s)
                data = s.encode("utf-8")
            zout.writestr(item, data)


def read_for_check(path: Path) -> str:
    if path.suffix in (".xlsx", ".docx", ".pptx"):
        with zipfile.ZipFile(path) as z:
            return " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith((".xml", ".rels")))
    if path.suffix in TEXT_EXT or path.name.startswith("."):
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def check(table) -> int:
    """コピー全体（中身とパス）に、置き換え表の語やメールアドレスが残っていないか調べる。"""
    hits = []
    for f in sorted(DEST.rglob("*")):
        if ".git" in f.relative_to(DEST).parts or not f.is_file():
            continue
        text = str(f.relative_to(DEST)) + "\n" + read_for_check(f)
        for pattern, _, word in table:
            n = len(pattern.findall(text))
            if n:
                hits.append(f"{f.relative_to(DEST)}：「{word}」{n}件")
        for mail in set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)):
            if not mail.endswith(("@anthropic.com", "@users.noreply.github.com", "@example.com")):
                hits.append(f"{f.relative_to(DEST)}：メールアドレス {mail}")
    for h in hits:
        print("  残り：", h)
    print(f"検査：置き換え漏れ {len(hits)} 件")
    return len(hits)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="検査だけ行う")
    args = parser.parse_args()
    table = load_table()
    if args.check:
        sys.exit(1 if check(table) else 0)

    DEST.mkdir(parents=True, exist_ok=True)
    made = set()
    sources = []
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)  # 上げないフォルダの中には入らない
        sources += [Path(folder) / f for f in files]
    for src in sorted(sources):
        rel = src.relative_to(ROOT)
        if excluded(rel):
            continue
        dst = DEST / Path(*[anonymize(p, table) for p in rel.parts])
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".xlsx":
            copy_xlsx(src, dst, table)
        elif src.suffix in (".docx", ".pptx"):
            copy_zip_xml(src, dst, table)
        elif src.suffix in TEXT_EXT or src.name.startswith("."):
            dst.write_text(anonymize(src.read_text(encoding="utf-8"), table), encoding="utf-8", newline="")
        else:
            shutil.copy2(src, dst)
        made.add(dst.resolve())

    stale_dir = STALE / datetime.now().strftime("%Y%m%d-%H%M%S")
    for f in sorted(DEST.rglob("*"), reverse=True):
        rel = f.relative_to(DEST)
        if ".git" in rel.parts or not f.is_file() or f.resolve() in made:
            continue
        move_into(f, (stale_dir / rel).parent)
        print(f"  前回のコピーにだけあったファイルを移動：{rel}")
    print(f"コピー：{len(made)} ファイル → {DEST.relative_to(ROOT)}")
    check(table)


if __name__ == "__main__":
    main()
