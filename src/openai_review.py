"""OpenAI の API で議事録をレビューする（レビュー Agent の OpenAI 版。docs/issue/issue_md/ISSUE-027）。

Claude のレビュー Agent（.claude/agents/minutes-reviewer.md）と同じ指示・同じ資料を OpenAI のモデルに渡し、
同じ形式の報告書（output_MeetingMinutes/<名前>/evidence_log/<名前>_議事録.review.md）を書く。

送るのは文字起こしなどのテキストだけで、音声は送らない。使う前に社内ルールを確認すること。

準備:
    1. setting/setting.xlsx の「モデル一覧」シートで openai の行の「呼び出し名」に OpenAI のモデル名を書き、「使える」にする
    2. 「議事録作成」シートの review_model を openai にする
    3. プロジェクト直下の .env に OPENAI_API_KEY=... を書く（.env は .gitignore 済み。チャットには貼らない）
    4. .venv/Scripts/python -m pip install openai

使い方（プロジェクトルートで。通常は議事録作成スキルの手順5-2から呼ばれる）:
    .venv/Scripts/python src/openai_review.py <名前>
"""

import contextlib
import io
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from paths import transcript_stem
from setting import review_agent

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / ".claude" / "agents" / "minutes-reviewer.md"
RULES = ROOT / ".claude" / "skills" / "minutes" / "references"


def api_key() -> str:
    """環境変数 OPENAI_API_KEY、なければプロジェクト直下の .env から読む。"""
    key = os.environ.get("OPENAI_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*OPENAI_API_KEY\s*=\s*['\"]?([^'\"\s]+)", line)
            if m:
                key = m.group(1)
    if not key:
        sys.exit("OPENAI_API_KEY がありません（環境変数か、プロジェクト直下の .env に書く）")
    return key


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else "（なし）"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    name = sys.argv[1]
    use, provider, model, reason = review_agent()
    if not use or provider != "OpenAI":
        sys.exit(f"setting.xlsx のレビュー Agent が OpenAI になっていません（{reason}）")

    stem = transcript_stem(name)
    transcript = Path(f"{stem}.speakers.txt") if Path(f"{stem}.speakers.txt").exists() else stem.with_suffix(".txt")
    evidence = ROOT / "output_MeetingMinutes" / name / "evidence_log"
    minutes = evidence / f"{name}_議事録.md"
    if not minutes.exists():
        sys.exit(f"議事録がありません：{minutes}")

    from glossary_tool import dump  # 用語集（Claude のレビュー Agent と同じ出力）

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dump()

    instructions = re.sub(r"^---.*?---\s*", "", AGENT.read_text(encoding="utf-8"), count=1, flags=re.S)
    materials = "\n\n".join([
        f"# 会議の名前\n{name}",
        f"# 文字起こし（{transcript.name}）\n{read(transcript)}",
        f"# テキストの文字起こし（Teams など。あれば）\n{read(Path(f'{stem}.text.txt'))}",
        f"# 議事録（{minutes.name}）\n{read(minutes)}",
        f"# 自己点検の結果\n{read(evidence / f'{name}_議事録.check.md')}",
        f"# 会議情報\n{read(ROOT / 'input' / f'{name}.会議情報.txt')}",
        f"# 書き方のルール\n{read(RULES / 'writing-rules.md')}",
        f"# 書式の固定仕様\n{read(RULES / 'format-spec.md')}",
        f"# 用語集\n{buf.getvalue()}",
        "# 依頼\n上の資料だけを使って、指示どおりにレビューし、報告書（Markdown）の本文だけを出力してください。"
        f"「レビュー担当」欄は「OpenAI（{model}）」としてください。ファイルの書き込みはこちらで行います。",
    ])

    from openai import OpenAI

    client = OpenAI(api_key=api_key())
    started = datetime.now()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": instructions}, {"role": "user", "content": materials}],
    )
    report = response.choices[0].message.content or ""
    out = evidence / f"{name}_議事録.review.md"
    out.write_text(report.strip() + "\n", encoding="utf-8")
    usage = response.usage
    print(f"{out.relative_to(ROOT)}（OpenAI {model}、{(datetime.now() - started).seconds}秒、"
          f"入力 {usage.prompt_tokens if usage else '?'} トークン / 出力 {usage.completion_tokens if usage else '?'} トークン）")


if __name__ == "__main__":
    main()
