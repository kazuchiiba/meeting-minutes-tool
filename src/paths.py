"""出力先のパス（会議ごとのフォルダ）。全スクリプト共通。

    transcripts/<名前>/<名前>.txt / .json / .speakers.txt / .meta.json / .timing.json ...
    output_MeetingMinutes/<名前>/<名前>_議事録[_VerN.0].docx   最新の Word だけを置く
    output_MeetingMinutes/<名前>/old/                          古い Word（新しい版を作ると自動で移す）
    output_MeetingMinutes/<名前>/evidence_log/                 議事録 md・自己点検（.check.md / .check.json）など Word 以外
    logs/                                                      実行ログ（*.log）

ファイルは消さない・上書きしない。片付けはすべて「移動」で行う（2026/11/23 Aさんの指示）。

<名前> は音声ファイル名（拡張子なし）。会議名は記録者が自由に付けるため、重ならない音声ファイル名をフォルダ名にする。
"""

import glob
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS = ROOT / "transcripts"
MINUTES = ROOT / "output_MeetingMinutes"
LOGS = ROOT / "logs"
OLD = "old"
EVIDENCE = "evidence_log"


def transcript_stem(name: str) -> Path:
    """transcripts/<名前>/<名前> を返す（拡張子は呼び出し側で付ける）。

    旧配置（transcripts 直下）のファイルが残っていれば、会議フォルダへ移してから返す。
    """
    folder = TRANSCRIPTS / name
    folder.mkdir(parents=True, exist_ok=True)
    for f in TRANSCRIPTS.glob(f"{glob.escape(name)}.*"):
        if f.is_file():
            f.replace(folder / f.name)
    return folder / name


def minutes_dir(name: str) -> Path:
    folder = MINUTES / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def evidence_dir(name: str) -> Path:
    """output_MeetingMinutes/<名前>/evidence_log/（議事録 md・自己点検の結果などを置く）。"""
    folder = minutes_dir(name) / EVIDENCE
    folder.mkdir(exist_ok=True)
    return folder


def meeting_folder_of(path: Path) -> Path:
    """evidence_log/ や old/ の中のファイルなら、その会議フォルダを返す。それ以外はファイルのあるフォルダ。"""
    return path.parent.parent if path.parent.name in (EVIDENCE, OLD) else path.parent


def move_into(src: Path, folder: Path) -> Path:
    """src を folder へ移す。同じ名前が既にあれば、名前の末尾に日時を付けて移す（上書きしない・消さない）。"""
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / src.name
    if dst.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = folder / f"{src.stem}_{stamp}{src.suffix}" if src.is_file() else folder / f"{src.name}_{stamp}"
    src.rename(dst)
    return dst


def archive_old_docx(folder: Path, latest: Path) -> list[Path]:
    """会議フォルダの直下にある同じ議事録の別の版（latest と同じ「<名前>_議事録」で始まる Word）を old/ へ移す。

    関係のない Word（名前の違うもの）と、Word で開いている時の一時ファイル（~$）は触らない。
    """
    base = re.sub(r"_Ver\d+(\.\d+)?$", "", latest.stem)
    moved = []
    for f in sorted(folder.glob(f"{glob.escape(base)}*.docx")):
        if f.name.startswith("~$") or f.resolve() == latest.resolve():
            continue
        moved.append(move_into(f, folder / OLD))
    return moved
