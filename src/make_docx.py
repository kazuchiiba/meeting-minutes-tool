"""議事録 md（人手版の書式）から、人手版と同じ書式の Word を作る。

人手版の Word をテンプレートとして複製し、冒頭の表・見出し・本文の段落書式（番号付きリストを含む）を引き継ぐ。
【推定】【聞き取り不明】【要確認】などの印は黄色の蛍光ペンで示す。

使い方:
    .venv/Scripts/python src/make_docx.py output_MeetingMinutes/<名前>/evidence_log/<名前>_議事録.md --type ヒアリング
    （--type：チェックイン / ヒアリング / その他。固定テンプレート .claude/skills/minutes/assets/ を使う。
      Word は会議フォルダ output_MeetingMinutes/<名前>/ の直下に保存する。
      既存の Word は消さず上書きもしない。同じ名前があれば _Ver2.0、_Ver3.0 … と版を上げて保存し、
      それより古い Word は old/ へ移す（会議フォルダの直下には常に最新の Word だけが残る）。版番号は old/ の中も見て決める）
      --template で任意の Word を指定することもできる）

md の書式:
    # 会議名
    | 日時 | 2026/11/20(金) |          ← 冒頭の表（日時・場所・参加者・資料）。参加者の改行は " / "
    【決定事項】                        ← 区切りの行（【…】だけの行）。そのまま段落になる
    - 決定事項                          ← 箇条書き（リスト2段目）
    【TODO】
    - 内容（担当：氏名、期限：…）
    【会議内容】
    ## 見出し                           ← 太字・下線の見出し（リスト1段目 ■）
    本文。(発言者)                      ← 会話のやり取りの最初の発言（リスト2段目 ➢）
      応答。(発言者)                    ← 行頭に半角スペース2つ：やり取りが一段落するまでの続き（リスト3段目 ✧）
    [(画像内容名)]                      ← 画面共有資料の差し込み枠。見出しの中のどこに書いても、その見出しの会話の最後に置く
    > 注記                              ← 末尾の【AI作成メモ】にまとめる（任意）
"""

import argparse
import copy
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.text.paragraph import Paragraph

from paths import OLD, archive_old_docx, meeting_folder_of

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / ".claude" / "skills" / "minutes" / "assets"
TEMPLATE_BY_TYPE = {  # 人手版の書式を固定仕様として持つ（docs/issue/issue_md/ISSUE-003）
    "チェックイン": TEMPLATES / "template_checkin.docx",
    "ヒアリング": TEMPLATES / "template_hearing.docx",
    "その他": TEMPLATES / "template_hearing.docx",
}
TABLE_ROWS = ["日時", "場所", "参加者", "資料"]
SECTION = re.compile(r"【[^】]{1,10}】")
MARK = re.compile(r"(【(?:推定|聞き取り不明|要確認|話者不明)[^】]*】)")


def parse(md: str) -> dict:
    doc = {"title": "", "table": {}, "notes": [], "blocks": []}
    for line in md.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("# "):
            doc["title"] = s[2:].strip()
        elif s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) >= 2 and cells[0] in TABLE_ROWS:
                doc["table"][cells[0]] = cells[1]
        elif s.startswith(">"):
            doc["notes"].append(s.lstrip("> ").strip())
        elif s.startswith("## "):
            doc["blocks"].append(("heading", s[3:].strip()))
        elif SECTION.fullmatch(s):
            doc["blocks"].append(("plain", s))
        elif s.startswith("[(") and s.endswith(")]"):
            doc["blocks"].append(("image", s))
        elif s.startswith("- "):
            doc["blocks"].append(("body", s[2:].strip()))
        elif line.startswith(("  ", "　")):  # 行頭の字下げ＝やり取りの続き
            doc["blocks"].append(("reply", s))
        else:
            doc["blocks"].append(("body", s))
    return doc


def images_last(blocks: list) -> list:
    """画像の枠を、それぞれの見出しの会話の最後に移す（docs/issue/issue_md/ISSUE-013）。"""
    out, pending = [], []
    for kind, text in blocks:
        if kind == "image":
            pending.append((kind, text))
            continue
        if kind in ("heading", "plain"):
            out += pending
            pending = []
        out.append((kind, text))
    return out + pending


def set_cell(cell, text: str) -> None:
    """セルの書式を残したまま文字を差し替える。" / " で段落を分ける。"""
    first = cell.paragraphs[0]
    for p in cell.paragraphs[1:]:
        p._p.getparent().remove(p._p)
    for r in first.runs:
        r._r.getparent().remove(r._r)
    lines = text.split(" / ") if text else [""]
    first.add_run(lines[0])
    for line in lines[1:]:
        new = copy.deepcopy(first._p)
        for r in new.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r"):
            new.remove(r)
        first._p.addnext(new)
        para = Paragraph(new, cell)
        para.add_run(line)
        first = para


def add_text(paragraph, text: str, bold=False, underline=False) -> None:
    for part in MARK.split(text):
        if not part:
            continue
        run = paragraph.add_run(part)
        run.bold = bold or None
        run.underline = underline or None
        if MARK.fullmatch(part):
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def next_version(path: Path) -> Path:
    """既存の Word は消さず・上書きせず、版を上げた名前を返す（2026/11/23 Aさんの指示）。

    <名前>_議事録.docx がなければそのまま（Ver1.0 扱い）。あれば <名前>_議事録_VerN.0.docx の N を、
    既存の版の最大＋1にする。
    """
    base = re.sub(r"_Ver\d+(\.\d+)?$", "", path.stem)
    versions = []
    for folder in (path.parent, path.parent / OLD):  # old/ に移した版も数える（版番号を戻さない）
        if (folder / f"{base}.docx").exists():
            versions.append(1.0)
        for p in folder.glob(f"{glob_escape(base)}_Ver*.docx"):
            m = re.fullmatch(rf"{re.escape(base)}_Ver(\d+(?:\.\d+)?)(?:_\d{{8}}-\d{{6}})?", p.stem)
            if m:
                versions.append(float(m.group(1)))
    if not versions:
        return path.parent / f"{base}.docx"
    return path.parent / f"{base}_Ver{int(max(versions)) + 1}.0.docx"


def glob_escape(s: str) -> str:
    import glob

    return glob.escape(s)


def build(md_path: Path, template: Path, out: Path | None = None) -> Path:
    data = parse(md_path.read_text(encoding="utf-8"))
    doc = Document(str(template))

    table = doc.tables[0]
    set_cell(table.rows[0].cells[0], data["title"])
    for i, key in enumerate(TABLE_ROWS, start=1):
        set_cell(table.rows[i].cells[1], data["table"].get(key, ""))

    # テンプレートから段落の書式見本を取る
    def ilvl(p):
        lv = p._p.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ilvl")
        return None if lv is None else lv.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")

    paras = doc.paragraphs
    marker = next(p for p in paras if p.text.strip() == "【会議内容】")
    heading_proto = next(p for p in paras if ilvl(p) == "0")
    body_proto = next(p for p in paras if ilvl(p) == "1")
    plain_proto = marker

    protos = {k: copy.deepcopy(p._p) for k, p in
              {"heading": heading_proto, "body": body_proto, "plain": plain_proto}.items()}
    for p in protos.values():
        for r in p.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r"):
            p.remove(r)
    # やり取りの続き：本文と同じリストの3段目（テンプレートでは ✧）
    protos["reply"] = copy.deepcopy(protos["body"])
    protos["reply"].find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ilvl").set(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "2")

    # 表より後ろの段落をすべて消す（sectPr は残す）
    body = doc.element.body
    after_table = False
    for el in list(body):
        if el is table._tbl:
            after_table = True
            continue
        if after_table and el.tag.endswith("}p"):
            body.remove(el)

    sect = body.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}sectPr")

    def append(kind: str, text: str, **fmt) -> None:
        el = copy.deepcopy(protos[kind])
        if sect is not None:
            sect.addprevious(el)
        else:
            body.append(el)
        add_text(Paragraph(el, doc._body), text, **fmt)

    blocks = images_last(data["blocks"])
    if ("plain", "【会議内容】") not in blocks:  # 旧書式の md は見出しの前に【会議内容】を補う
        first = next((i for i, (k, _) in enumerate(blocks) if k == "heading"), 0)
        blocks = blocks[:first] + [("plain", "【会議内容】")] + blocks[first:]
    append("plain", "")
    for i, (kind, text) in enumerate(blocks):
        if kind == "heading":
            append("heading", text, bold=True, underline=True)
        elif kind == "plain":
            if i > 0:
                append("plain", "")  # 区切りの前に1行空ける
            append("plain", text)
        elif kind == "image":
            append("plain", text)  # 箇条書きにしない
        elif kind == "reply":
            append("reply", text)
        else:
            append("body", text)
    if data["notes"]:
        append("plain", "")
        append("plain", "【AI作成メモ】")
        for note in data["notes"]:
            append("body", note)

    doc.core_properties.title = data["title"]
    doc.core_properties.author = "Claude（自動作成）"
    out = next_version(out or meeting_folder_of(md_path) / f"{md_path.stem}.docx")
    doc.save(str(out))
    for moved in archive_old_docx(out.parent, out):
        print(f"古い Word を移動：{moved.relative_to(out.parent)}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("md", type=Path)
    parser.add_argument("--type", choices=list(TEMPLATE_BY_TYPE), default="ヒアリング", help="会議の種類")
    parser.add_argument("--template", type=Path, default=None, help="テンプレートの Word を直接指定する場合")
    parser.add_argument("--out", type=Path, default=None, help="出力する Word のパス（既定：会議フォルダ直下に md と同じ名前の .docx）")
    args = parser.parse_args()
    print(build(args.md, args.template or TEMPLATE_BY_TYPE[args.type], args.out))


if __name__ == "__main__":
    main()
