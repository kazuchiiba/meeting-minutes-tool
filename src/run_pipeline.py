"""音声から話者付き文字起こしまでを一括で実行し、工程ごとの処理時間を記録する。

工程：① 文字起こし（.venv）→ ② 話者分離（.venv-diar）→ ③ 抜けの補完（.venv）
実行中は Windows のスリープを抑止する（検証時、スリープで約7.5時間止まったため）。
②を行うかは、会議情報ファイルの「話者分離」欄 ＞ setting/setting.xlsx の順で決める（既定は「しない」。ISSUE-024）。
②の窓のずらし幅などは setting/setting.xlsx で変えられる（src/setting.py）。

入力は3通り（docs/issue/issue_md/ISSUE-002）。音声とテキストは同じ名前（拡張子だけ違う）で input/ に置けば自動で組み合わせる。
    音声のみ         ① 文字起こし → ② 話者分離 → ③ 抜けの補完（②を行わない設定なら ① → ③）
    テキストのみ     テキストの取り込み（Teams .vtt / .docx、Notion .txt / .md など）
    テキスト＋音声   ① 文字起こし → ③ 抜けの補完 → テキストの取り込み → 話者の対応付け（話者名はテキストから。②は不要）

使い方（プロジェクトルートで）:
    .venv/Scripts/python src/run_pipeline.py INPUT/<名前>.m4a --speakers <参加人数>
    .venv/Scripts/python src/run_pipeline.py INPUT/<名前>.m4a --no-diarize   # ②を飛ばす検証用（<名前>_話者分離なし に出力）
    .venv/Scripts/python src/run_pipeline.py INPUT/<名前>.vtt                # テキストのみ（同名の音声があれば テキスト＋音声）
    .venv/Scripts/python src/run_pipeline.py INPUT/<名前>.m4a --text INPUT/<別名>.docx   # テキストを明示する

出力:
    transcripts/<名前>/<名前>.*            各工程の出力
    transcripts/<名前>/<名前>.timing.json  工程ごとの開始・終了時刻と処理時間
    （--no-diarize の場合、または②を行わない設定で、話者分離済みの結果が既にある場合は、
      <名前>_話者分離なし という名前で出力し、通常の結果を上書きしない）
"""

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from paths import transcript_stem
from setting import diarize_args, diarize_enabled, whisper_hotwords

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY_DIAR = ROOT / ".venv-diar" / "Scripts" / "python.exe"

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake(on: bool) -> None:
    """Windows のスリープ（アイドル時）を抑止 / 解除する。蓋を閉じた時の動作は電源設定に従う。"""
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def reuse_srt(src: Path, dst: Path) -> int:
    """既存の文字起こしの .srt（③の補完で書き換えられない、Whisper の元の出力）から、.json / .txt / .meta.json を作る。"""
    rows = []
    for block in src.with_suffix(".srt").read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        to_sec = lambda t: sum(float(x) * m for x, m in zip(t.replace(",", ".").split(":"), (3600, 60, 1)))
        start, end = (to_sec(t.strip()) for t in lines[1].split("-->"))
        rows.append({"id": len(rows) + 1, "start": start, "end": end, "text": " ".join(lines[2:]).strip()})
    fmt = lambda s: f"{int(s) // 3600:02}:{int(s) % 3600 // 60:02}:{int(s) % 60:02}"
    dst.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    dst.with_suffix(".txt").write_text("\n".join(f"[{fmt(r['start'])}] {r['text']}" for r in rows) + "\n", encoding="utf-8")
    dst.with_suffix(".srt").write_text(src.with_suffix(".srt").read_text(encoding="utf-8"), encoding="utf-8")
    meta = json.loads(Path(f"{src}.meta.json").read_text(encoding="utf-8"))
    meta = {k: v for k, v in meta.items() if k not in ("diarization", "gap_fill")}
    meta["note"] = f"文字起こしは {src.name}.srt（Whisper の元の出力）を再利用。話者分離なし。"
    Path(f"{dst}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(rows)


AUDIO_EXT = [".m4a", ".mp3", ".wav", ".mp4", ".aac", ".flac", ".ogg", ".webm", ".mov"]
TEXT_EXT = [".vtt", ".docx", ".txt", ".md"]


def find_pair(path: Path, exts: list[str]) -> Path | None:
    """同じ名前で拡張子だけ違うファイルを探す（会議情報ファイル <名前>.会議情報.txt は対象外）。"""
    for ext in exts:
        p = path.with_suffix(ext)
        if p.exists() and p != path:
            return p
    return None


def fill_participants(info: Path, speakers: list[str]) -> None:
    """テキストの話者名を、会議情報ファイルの参加者欄に入れる（空欄のときだけ。なければひな形を作る）。"""
    if not speakers:
        return
    if not info.exists():
        from meeting_info import template

        info.write_text(template(info.with_name(info.name.replace(".会議情報.txt", ".txt")), speakers, "A"),
                        encoding="utf-8")
        print(f"会議情報ファイルを作りました（参加者はテキストの話者名）：{info.name}")
        return
    text = info.read_text(encoding="utf-8")
    if "\n参加者: \n" in text or text.rstrip().endswith("参加者:"):
        info.write_text(text.replace("参加者: \n", f"参加者: {'、'.join(speakers)}\n", 1), encoding="utf-8")
        print(f"会議情報ファイルの参加者欄に、テキストの話者名を入れました：{'、'.join(speakers)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="音声ファイル、またはテキストファイル（Teams・Notion）")
    parser.add_argument("--text", type=Path, default=None, help="組み合わせるテキストファイル（既定：同じ名前のもの）")
    parser.add_argument("--name", default=None, help="出力先の名前（既定：入力ファイル名）")
    parser.add_argument("--speakers", type=int, default=None, help="参加人数")
    parser.add_argument("--no-diarize", action="store_true", help="②話者分離（pyannote）を飛ばす")
    args = parser.parse_args()

    src = args.input.resolve()
    if src.suffix.lower() in TEXT_EXT:
        text, audio = src, find_pair(src, AUDIO_EXT)
    else:
        audio, text = src, (args.text.resolve() if args.text else find_pair(src, TEXT_EXT))
    mode = "テキスト＋音声" if audio and text else ("テキストのみ" if text else "音声のみ")
    base = src.stem
    diarize, diarize_reason = False, "テキストの話者名を使う（②は不要）"
    if mode == "音声のみ":
        if args.no_diarize:
            diarize, diarize_reason = False, "コマンドの --no-diarize（検証用）"
        else:
            diarize, diarize_reason = diarize_enabled(src.with_name(f"{base}.会議情報.txt"))
    no_diar_name = args.no_diarize or (not diarize and Path(f"{transcript_stem(base)}.diarization.json").exists())
    name = args.name or (f"{base}_話者分離なし" if mode == "音声のみ" and no_diar_name else base)
    if mode == "テキスト＋音声" and not args.name and Path(f"{transcript_stem(base)}.diarization.json").exists():
        name = f"{base}_テキスト併用"  # 「音声のみ」で処理済みの会議は、その結果を上書きしない
    stem = transcript_stem(name)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_DISABLE_SYMLINKS_WARNING="1")
    speakers = ["--speakers", str(args.speakers)] if args.speakers else []
    timing = {"input": src.name, "mode": mode, "text": text.name if text else None, "audio": audio.name if audio else None,
              "diarize": diarize, "diarize_reason": diarize_reason, "speakers": args.speakers, "steps": []}
    print(f"入力：{mode}（音声：{audio.name if audio else 'なし'}、テキスト：{text.name if text else 'なし'}）→ {name}", flush=True)
    if mode == "音声のみ":
        print(f"② 話者分離（pyannote）：{'する' if diarize else 'しない'}（{diarize_reason}）", flush=True)

    if mode == "テキストのみ":
        steps = [("テキストの取り込み", [str(PY), "src/import_text.py", "import", name, str(text), "--text-only"])]
    elif mode == "テキスト＋音声":
        source = transcript_stem(audio.stem)
        if source.with_suffix(".srt").exists():  # 同じ音声の文字起こしがあれば、やり直さずに再利用する
            n = reuse_srt(source, stem)
            print(f"① 文字起こし：既存の {source.name}.srt を再利用（{n} セグメント）", flush=True)
            timing["steps"].append({"step": "① 文字起こし（既存を再利用）", "elapsed_min": 0.0, "returncode": 0})
            steps = []
        else:
            steps = [("① 文字起こし", [str(PY), "src/transcribe.py", str(audio), "--name", name])]
        steps += [
            ("③ 抜けの補完", [str(PY), "src/fill_gaps.py", str(audio), "--name", name, "--no-diarize"]),
            ("テキストの取り込み", [str(PY), "src/import_text.py", "import", name, str(text)]),
            ("話者の対応付け", [str(PY), "src/import_text.py", "align", name]),
        ]
    elif not diarize:
        source = transcript_stem(audio.stem)
        if source.with_suffix(".srt").exists():  # 同じ音声の文字起こしがあれば、やり直さずに再利用する
            n = reuse_srt(source, stem)
            print(f"① 文字起こし：既存の {source.name}.srt を再利用（{n} セグメント）", flush=True)
            timing["steps"].append({"step": "① 文字起こし（既存を再利用）", "elapsed_min": 0.0, "returncode": 0})
            steps = []
        else:
            steps = [("① 文字起こし", [str(PY), "src/transcribe.py", str(audio), "--name", name])]
        steps.append(("③ 抜けの補完", [str(PY), "src/fill_gaps.py", str(audio), "--name", name, "--no-diarize"]))
    else:
        if name != audio.stem:
            sys.exit("音声のみの通常処理では --name は使えません（②話者分離の出力先が音声ファイル名で決まるため）")
        steps = [
            ("① 文字起こし", [str(PY), "src/transcribe.py", str(audio)]),
            ("② 話者分離", [str(PY_DIAR), "src/diarize.py", str(audio), *speakers, *diarize_args()]),
            ("③ 抜けの補完", [str(PY), "src/fill_gaps.py", str(audio)]),
        ]

    # Whisper に渡す語（会議情報ファイル ＞ setting.xlsx。docs/issue/issue_md/ISSUE-025）
    if audio:
        hotwords, reason = whisper_hotwords(src.with_name(f"{base}.会議情報.txt"))
        timing["hotwords"] = {"words": hotwords, "reason": reason}
        print(f"Whisper に渡す語：{reason}{'：' + hotwords if hotwords else ''}", flush=True)
        if hotwords:
            for _, cmd in steps:
                if cmd[1] in ("src/transcribe.py", "src/fill_gaps.py"):
                    cmd += ["--hotwords", hotwords]

    keep_awake(True)
    try:
        for step_name, cmd in steps:
            started = datetime.now()
            t0 = time.time()
            print(f"[{started:%H:%M:%S}] {step_name} 開始", flush=True)
            result = subprocess.run(cmd, cwd=ROOT, env=env)
            elapsed = time.time() - t0
            timing["steps"].append({
                "step": step_name,
                "start": started.isoformat(timespec="seconds"),
                "end": datetime.now().isoformat(timespec="seconds"),
                "elapsed_min": round(elapsed / 60, 1),
                "returncode": result.returncode,
            })
            Path(f"{stem}.timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[{datetime.now():%H:%M:%S}] {step_name} 終了（{elapsed / 60:.1f}分）", flush=True)
            if result.returncode != 0:
                sys.exit(f"{step_name} が失敗しました（終了コード {result.returncode}）")
    finally:
        keep_awake(False)
    if text:  # テキストの話者名を、会議情報ファイルの参加者欄に入れる
        rows = json.loads(Path(f"{stem}.text.json").read_text(encoding="utf-8"))
        names = list(dict.fromkeys(r["speaker"] for r in rows if r["speaker"]))
        fill_participants(src.with_name(f"{base}.会議情報.txt"), names)
    total = sum(s["elapsed_min"] for s in timing["steps"])
    print(f"完了：合計 {total:.1f}分 → {stem}.speakers.txt")


if __name__ == "__main__":
    main()
