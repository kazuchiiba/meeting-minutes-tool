"""setting/setting.xlsx（記録者が変えられる処理のパラメータ）の読み出し。run_pipeline.py から使う（.venv）。

Excel の各シートの「キー」列で項目を見分け、「設定値」列の値を使う。空欄・ファイルがない場合は既定値。
pyannote の .venv-diar には openpyxl がないので、ここで読んだ値をコマンドの引数にして diarize.py に渡す。
"""

import re
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
SETTING = ROOT / "setting" / "setting.xlsx"

AUTO = "自動"
DEFAULTS = {
    "whisper_glossary": "渡す",  # 文字起こし：Whisper に用語集を渡すか（docs/issue/issue_md/ISSUE-025）
    "whisper_glossary_max_chars": 120,  # 文字起こし：渡す語の上限（文字数）。Whisper の上限はおよそ100〜150字
    "diar_enabled": "しない",  # 話者分離：②（pyannote）を行うか（docs/issue/issue_md/ISSUE-024）
    "diar_shift_sec": 2.0,  # 話者分離：10秒の窓をずらす幅（秒）。精度をほぼ保ち約2倍速（ISSUE-018。pyannote 本来は 1.0）
    "diar_min_cluster_size": AUTO,  # 話者分離：1話者あたりの最低特徴量数
}
WINDOW_SEC = 10.0  # pyannote/segmentation-3.0 の窓の長さ
SHIFT_RANGE = (0.5, 5.0)


def load(path: Path = SETTING) -> dict:
    values = dict(DEFAULTS)
    if not path.exists():
        return values
    wb = load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        header = [str(c).strip() if c is not None else "" for c in next(rows, [])]
        if "キー" not in header or "設定値" not in header:
            continue
        k, v = header.index("キー"), header.index("設定値")
        for row in rows:
            if row[k] in DEFAULTS and row[v] not in (None, ""):
                values[row[k]] = row[v]
    wb.close()
    return values


def diarize_args(values: dict | None = None) -> list[str]:
    """diarize.py に渡す --step / --min-cluster-size。値がおかしければ理由を示して止める。"""
    values = values or load()
    shift = float(values["diar_shift_sec"])
    if not SHIFT_RANGE[0] <= shift <= SHIFT_RANGE[1]:
        raise SystemExit(f"{SETTING.name}：窓のずらし幅は {SHIFT_RANGE[0]}〜{SHIFT_RANGE[1]} 秒で指定してください（今の値 {shift}）")
    args = ["--step", f"{shift / WINDOW_SEC:g}"]
    mcs = values["diar_min_cluster_size"]
    if str(mcs).strip() != AUTO:
        if not (isinstance(mcs, (int, float)) and float(mcs).is_integer() and mcs >= 2):
            raise SystemExit(f"{SETTING.name}：最低特徴量数は「{AUTO}」か 2 以上の整数で指定してください（今の値 {mcs}）")
        args += ["--min-cluster-size", str(int(mcs))]
    return args


DO, DONT = "する", "しない"


def diarize_enabled(info_file: Path | None, values: dict | None = None) -> tuple[bool, str]:
    """②話者分離（pyannote）を行うかと、その理由を返す（ISSUE-024）。

    優先順位：会議情報ファイルの「話者分離」欄 ＞ setting.xlsx の diar_enabled。
    """
    values = values or load()
    info = {}
    if info_file and info_file.exists():
        from meeting_info import parse

        info = parse(info_file.read_text(encoding="utf-8"))
    choice = (info.get("話者分離") or "").strip()
    source = "会議情報ファイル" if choice else SETTING.name
    choice = choice or str(values["diar_enabled"]).strip()
    if choice not in (DO, DONT):
        raise SystemExit(f"{source}：「話者分離」は「{DO}」か「{DONT}」で指定してください（今の値 {choice}）")
    return choice == DO, f"{source}の設定で{choice}"


GLOSSARY = ROOT / "docs" / "design" / "議事録作成用の用語集.xlsx"
GIVE, NOT_GIVE = "渡す", "渡さない"


def whisper_hotwords(info_file: Path | None, values: dict | None = None) -> tuple[str | None, str]:
    """Whisper に渡す語（hotwords）と、その理由を返す。渡さない場合は (None, 理由)。

    優先順位：会議情報ファイルの「Whisper に用語集を渡す」欄 ＞ setting.xlsx の whisper_glossary。
    渡す語：参加者名 → 会議情報ファイルの「Whisper に渡す追加の語」 → 用語集の確認済みの語（誤変換例の多い順）。
    whisper_glossary_max_chars の文字数まで入れる。
    """
    values = values or load()
    info = {}
    if info_file and info_file.exists():
        from meeting_info import parse

        info = parse(info_file.read_text(encoding="utf-8"))
    choice = (info.get("Whisperに用語集を渡す") or "").strip()
    source = "会議情報ファイル" if choice else SETTING.name
    choice = choice or str(values["whisper_glossary"]).strip()
    if choice == NOT_GIVE:
        return None, f"{source}の設定で渡さない"
    if choice != GIVE:
        raise SystemExit(f"{source}：「Whisper に用語集を渡す」は「{GIVE}」か「{NOT_GIVE}」で指定してください（今の値 {choice}）")
    max_chars = int(values["whisper_glossary_max_chars"])
    if not 20 <= max_chars <= 200:
        raise SystemExit(f"{SETTING.name}：渡す語の上限は 20〜200 文字で指定してください（今の値 {max_chars}）")

    words = list(info.get("参加者", []))
    words += [w.strip() for w in re.split(r"[、,]", info.get("Whisperに渡す追加の語", "")) if w.strip()]
    if GLOSSARY.exists():
        wb = load_workbook(GLOSSARY, read_only=True)
        scored = []
        for sheet in ("用語", "人名"):
            if sheet not in wb.sheetnames:
                continue
            for row in wb[sheet].iter_rows(min_row=2, values_only=True):
                if not row[1] or row[5] != "確認済":
                    continue
                misreads = [m for m in re.split(r"[、,\n]", str(row[3] or "")) if m.strip() and m.strip() not in ("—", "-", "None")]
                for name in re.split(r"\s*/\s*", re.sub(r"（.*?）|\(.*?\)", "", str(row[1]))):
                    if name.strip():
                        scored.append((len(misreads), name.strip()))
        wb.close()
        words += [w for _, w in sorted(scored, key=lambda x: -x[0])]
    picked, length = [], 0
    for w in dict.fromkeys(words):  # 重複を除き、順番を保つ
        if length + len(w) + 1 > max_chars:
            continue
        picked.append(w)
        length += len(w) + 1
    return ("、".join(picked) or None), f"{source}の設定で渡す（{len(picked)}語・{length}文字）"


if __name__ == "__main__":
    print(load())
    print(diarize_args())
    print(diarize_enabled(None))
    print(whisper_hotwords(None))
