"""会議情報ファイル（INPUT/<名前>.会議情報.txt）のひな形作成と読み込み。

記録者が議事録作成の前に記入する（docs/issue/issue_md/ISSUE-001・008）。予定表とは連携しない。
会議名は記録者が決める。既定値は入力ファイル名（音声ファイル名、テキスト入力ならテキストファイル名。拡張子なし）。
話者対応表が空欄の場合は、議事録作成の前に Claude が文字起こしから推定して「（AI推定）」付きで書き込む。

使い方:
    .venv/Scripts/python src/meeting_info.py init INPUT/<名前>.m4a --participants C,A [--recorder A]
    .venv/Scripts/python src/meeting_info.py show INPUT/<名前>.m4a
"""

import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEEKDAYS = "月火水木金土日"
FIELDS = ["会議名", "日時", "場所", "会議の種類", "記録者", "参加者", "資料", "話者分離", "Whisperに用語集を渡す", "Whisperに渡す追加の語"]
TYPES = ["チェックイン", "ヒアリング", "その他"]


def info_path(audio: Path) -> Path:
    return audio.with_name(f"{audio.stem}.会議情報.txt")


def template(audio: Path, participants: list[str], recorder: str, values: dict | None = None) -> str:
    """会議情報ファイルの本文。説明は「#」の行に分け、値の欄はコロンの後ろだけにする。

    values：既存のファイルから読んだ値（parse の結果）。指定すると記入済みの値と話者対応表を引き継ぐ。
    """
    v = values or {}
    m = re.match(r"(\d{4})(\d{2})(\d{2})", audio.stem)
    day = ""
    if m:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        day = f"{d:%Y/%m/%d}({WEEKDAYS[d.weekday()]})"
    joined = lambda x: "、".join(x) if isinstance(x, list) else (x or "")
    lines = [
        "# 会議情報（議事録作成の前に記録者が記入する）",
        "# 「#」で始まる行は説明。値はコロン（:）の後ろに書く。空欄の項目は議事録でも空欄になる。",
        "",
        "# 議事録の題名（既定は入力ファイル名）",
        f"会議名: {v.get('会議名') or audio.stem}",
        f"日時: {v.get('日時') or day}",
        f"場所: {v.get('場所', '')}",
        f"# {' / '.join(TYPES)} から1つ（Word の書式が変わる。空欄なら AI が冒頭のやり取りから判断）",
        f"会議の種類: {v.get('会議の種類', '')}",
        f"記録者: {v.get('記録者') or recorder}",
        "# 氏名を「、」区切りで（所属は用語集の「人名」シートから付く）",
        f"参加者: {joined(v.get('参加者')) or joined(participants)}",
        f"資料: {v.get('資料', '')}",
        "",
        "# 以下は処理の設定。空欄なら setting/setting.xlsx の設定に従う（この会議だけ変えるときに書く）",
        "# する / しない",
        f"話者分離: {v.get('話者分離', '')}",
        "# 渡す / 渡さない",
        f"Whisperに用語集を渡す: {v.get('Whisperに用語集を渡す', '')}",
        "# この会議で出てきそうな固有名詞などを「、」区切りで（任意）",
        f"Whisperに渡す追加の語: {v.get('Whisperに渡す追加の語', '')}",
        "",
        "# 話者対応表（「SPEAKER_00: 氏名」の形で1行ずつ）。話者分離をしない場合は不要",
        "# 空欄なら議事録作成の前に AI が推定して「（AI推定）」付きで記入する",
        "# 話者ごとの発言例は .venv/Scripts/python src/speaker_samples.py transcripts/<名前>/<名前>.json で確認できる",
        "[話者対応表]",
    ]
    lines += [f"{k}: {val}" for k, val in (v.get("話者対応表") or {}).items()]
    return "\n".join(lines) + "\n"


def parse(text: str) -> dict:
    info = {k: "" for k in FIELDS}
    info["話者対応表"] = {}
    in_map = False
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s == "[話者対応表]":
            in_map = True
            continue
        key, _, value = s.partition(":")
        key, value = key.strip(), value.strip()
        if in_map:
            if key:
                info["話者対応表"][key] = value
        elif key in FIELDS:
            # ひな形の説明書き（「（空欄なら…）」など）は値として扱わない。値の後ろに残っていても除く
            value = re.sub(r"\s*（[^）]*(空欄なら|から1つ|任意)[^）]*）", "", value).strip()
            info[key] = value
    info["参加者"] = [p.strip() for p in re.split(r"[、,]", info["参加者"]) if p.strip()]
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("audio", type=Path)
    i.add_argument("--participants", default="")
    i.add_argument("--recorder", default="A")
    f = sub.add_parser("reformat", help="既存の会議情報ファイルを今のひな形の形に直す（記入済みの値は引き継ぐ）")
    f.add_argument("audio", type=Path)
    s = sub.add_parser("show")
    s.add_argument("audio", type=Path)
    args = parser.parse_args()

    path = info_path(args.audio)
    if args.cmd == "init":
        if path.exists():
            print(f"既にあります（上書きしません）：{path}")
        else:
            path.write_text(template(args.audio, [p for p in re.split(r"[、,]", args.participants) if p], args.recorder),
                            encoding="utf-8")
            print(f"作成しました：{path}")
        return

    if args.cmd == "reformat":
        values = parse(path.read_text(encoding="utf-8"))
        path.write_text(template(args.audio, values["参加者"], values["記録者"] or "A", values), encoding="utf-8")
        print(f"今の形に直しました：{path}")
        return

    if not path.exists():
        raise SystemExit(f"会議情報ファイルがありません：{path}（init で作成し、記録者に記入してもらう）")
    info = parse(path.read_text(encoding="utf-8"))
    if not info["会議名"]:
        info["会議名"] = args.audio.stem  # 空欄なら入力ファイル名を使う
    print(json.dumps(info, ensure_ascii=False, indent=1))
    missing = [k for k in ("会議の種類", "参加者") if not info[k]]
    if missing:
        print(f"未記入：{'、'.join(missing)}（記録者に確認する）")
    from setting import diarize_enabled

    diarize, reason = diarize_enabled(path)
    print(f"話者分離（pyannote）：{'する' if diarize else 'しない'}（{reason}）")
    if not diarize:
        print("話者分離なし：話者対応表は使わない（Claude が発言内容から発言者を推定する）")
    elif not info["話者対応表"] or any(not v for v in info["話者対応表"].values()):
        print("話者対応表が未記入（Claude が推定して「（AI推定）」付きで記入し、該当の発言者に【推定】を付ける）")


if __name__ == "__main__":
    main()
