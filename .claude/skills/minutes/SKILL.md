---
name: minutes
description: 会議の録音（.m4a など）から、人手版と同じ書式の Word 議事録を作る。文字起こし・話者分離・抜けの補完をローカルで実行し、話者対応表と用語集を使って議事録を書き、自己点検・Word 出力・用語集の追加候補の通知までを行う。「議事録を作って」「録音から議事録」「この音声を文字起こしして議事録に」「会議の音声を処理して」と頼まれたら使う。文字起こし済みのテキストから議事録を作る場合にも使う。
---

# 議事録作成

会議の録音から、事実に忠実な Word 議事録を作る。**最優先は正しい事実としての議事録**（発言にないことを書かない、拾える発言を漏らさない）。速度は後回し。

全体の設計・環境構築は `docs/design/議事録作成ツール設計書.md`、書き方のルールは [references/writing-rules.md](references/writing-rules.md)、書式の固定仕様は [references/format-spec.md](references/format-spec.md) を参照する。コマンドはすべてプロジェクトルート（`20261122_Voice_Translate_2`）で実行する。

## 守ること

- **会議の音声を、クラウドサービスや外部 API に送らない。** 文字起こし・話者分離はローカルの `src/` のスクリプトだけで行う。
- 検証で人手版の議事録（INPUT の .docx）と比べる場合は、**Word を出力し終えるまで人手版を開かない**（盲検）。
- 用語集（`docs/design/議事録作成用の用語集.xlsx`）は記録者が編集する正本。「候補」シートへの追記以外は、記録者の確認なしに書き換えない。
- 記録者が決めていないことを決めない。新しい論点が出たら `issue` スキルで起票する。

## 手順

### 0. 入力と会議情報を確かめる

- 音声ファイルの場所と長さを確認する。
- 会議情報ファイル（`INPUT/<名前>.会議情報.txt`）を読む。なければひな形を作り、**記録者に記入してもらう**（会議名・会議の種類・参加者。会議名は記録者が決める。既定値は入力ファイル名。予定表とは連携しない）。

```powershell
.venv\Scripts\python src\meeting_info.py init INPUT\<名前>.m4a --participants 氏名,氏名
.venv\Scripts\python src\meeting_info.py show INPUT\<名前>.m4a
```
- 入力は3通り（docs/issue/issue_md/ISSUE-002）。音声とテキストは**同じ名前（拡張子だけ違う）**で `input/` に置く。
  - 音声のみ：①文字起こし → ②話者分離 → ③抜けの補完
  - テキストのみ（Teams `.vtt` / `.docx`、Notion `.txt` / `.md` など）：テキストを取り込むだけ（音声の処理なし）
  - テキスト＋音声：①（既存の `.srt` があれば再利用）→ ③ → テキストの取り込み → 話者の対応付け。**話者名はテキストから付けるので②は不要**
  - テキストに話者名があれば、会議情報ファイルの参加者欄に自動で入る（空欄のときだけ）。

### 1. ①〜③ 文字起こし・話者分離・抜けの補完

```powershell
.venv\Scripts\python src\run_pipeline.py INPUT\<名前>.m4a --speakers <参加人数>   # 音声（同名のテキストがあれば テキスト＋音声）
.venv\Scripts\python src\run_pipeline.py INPUT\<名前>.vtt                       # テキスト（同名の音声があれば テキスト＋音声）
```

- 「音声のみ」で処理済みの会議にテキストを足した場合は、`transcripts/<名前>_テキスト併用/` に出力し、既存の結果を上書きしない。
- ②話者分離（pyannote）を行うかは、会議情報ファイルの `話者分離:` 欄（する / しない）＞ `setting/setting.xlsx` の順で決まる（既定は「しない」。docs/issue/issue_md/ISSUE-024）。実行時に「② 話者分離（pyannote）：する / しない（理由）」と表示される。「しない」で、話者分離済みの結果が既にある会議は `transcripts/<名前>_話者分離なし/` に出力する。

- 時間がかかる（CPU で音声の数倍）ので、バックグラウンドで実行し、終わるまで待つ。出力は `logs/run_<名前>.log` に残す（プロジェクト直下にログを置かない）。処理時間は `transcripts/<名前>/<名前>.timing.json` に記録される。
- 実行中に PC がスリープしないよう、記録者に伝える（蓋を閉じない）。

### 2. 話者対応表を確かめる

- **テキストのみ・テキスト＋音声では、話者名はテキストのものを使う**（話者対応表は不要）。
- **話者分離を「しない」で処理した会議では、話者対応表は使わない。** `.speakers.txt` には話者記号がないので、指名・呼びかけ・自己言及・質問と回答の流れから発言者を推定し、writing-rules の規則11（確度が高ければ `(氏名)`、怪しければ `(氏名【推定】)`、分からなければ `(不明)`）に従って書く。聞き手が複数いる会議では聞き手どうしの区別が難しいので、無理に断定しない（ISSUE-024）。
- 会議情報ファイルの `[話者対応表]` に記入があれば、それを使う。
- 空欄なら、話者ごとの発言例から Claude が推定し、`SPEAKER_00: 氏名（AI推定）` の形でファイルに書き込む。推定した人の発言には `(氏名【推定】)` を付ける。推定結果は記録者に伝え、直してもらえれば作り直す（ヒアリング形式で Claude の推定が外れたことがある。docs/issue/issue_md/ISSUE-001）。

```powershell
.venv\Scripts\python src\speaker_samples.py transcripts\<名前>\<名前>.json
```

- 1つの記号に2人が混ざっている場合は、記録者に伝え、発言内容から振り分けた箇所に【推定】を付ける。

### 3. 用語集を読む

```powershell
.venv\Scripts\python src\glossary_tool.py dump
```

正式表記・意味・誤変換例を頭に入れてから書く。

### 4. ④ 議事録の md を書く

```powershell
.venv\Scripts\python src\timing.py <名前> start "④ 議事録の作成"
```

- `transcripts/<名前>/<名前>.speakers.txt` を**最初から最後まで**読み（テキスト＋音声では `<名前>.text.txt`＝テキストの本文も読み、突き合わせる）、[references/writing-rules.md](references/writing-rules.md) に従って `output_MeetingMinutes/<名前>/evidence_log/<名前>_議事録.md` を書く。
- 長い会議でも要約しない。本文では具体例・経緯を省かない。

```powershell
.venv\Scripts\python src\timing.py <名前> end "④ 議事録の作成"
```

### 5. ⑤ 自己点検して直す

```powershell
.venv\Scripts\python src\check_coverage.py transcripts\<名前>\<名前>.json output_MeetingMinutes\<名前>\evidence_log\<名前>_議事録.md
```

- `output_MeetingMinutes/<名前>/evidence_log/<名前>_議事録.check.md` の候補を**1件ずつ**文字起こしと見比べる。
  - 抜けの候補：本当に抜けていれば本文に足す。言い換えて書いてある、または意味の取れない断片なら対応不要。
  - 根拠のない語の候補：文字起こしにない語に言い換えていれば、【推定：「元の語」】を付けるか、文字起こしどおりに直す。
- 直したら再実行し、本当の抜け・言い換えがなくなるまで繰り返す。

### 5-2. レビュー Agent に点検させる（設定が「使う」のとき）

```powershell
.venv\Scripts\python src\setting.py review
```

- `review_agent=使う provider=OpenAI` なら、Agent ツールは使わず、次を実行する（同じ指示・同じ資料を OpenAI の API に送る。送るのはテキストだけで音声は送らない。API キーはプロジェクト直下の `.env`）。
```powershell
.venv\Scripts\python src\openai_review.py <名前>
```
- `review_agent=使う provider=Claude` なら、**Agent ツールで `minutes-reviewer` を呼ぶ**（`.claude/agents/minutes-reviewer.md`）。モデルは表示された `model`（`sonnet` など）を Agent ツールの `model` に指定する。「書き手と同じ」なら指定しない。
- モデルの選択肢は `setting/setting.xlsx` の「モデル一覧」シート。新しいモデルは行を足せば選べる（docs/issue/issue_md/ISSUE-027）。
  - `minutes-reviewer` が使えない環境（プロジェクトのフォルダ以外で Claude Code を起動した場合など）では、`general-purpose` の Agent に `.claude/agents/minutes-reviewer.md` を読ませて同じ役割をさせる。
  - Agent への依頼文には、会議の名前とプロジェクトのフォルダだけを書く。**書き手の判断や自分の議事録への評価は書かない**（独立した目を保つため）。
- 報告書 `output_MeetingMinutes/<名前>/evidence_log/<名前>_議事録.review.md` の指摘を1件ずつ文字起こしで確かめ、正しい指摘なら議事録を直す。直さない指摘は、理由を報告書の末尾に「書き手の判断」として追記する。
- 直したら⑤の自己点検を再実行する。
- `review_agent=使わない` なら、この手順は飛ばす。

### 6. ⑥ Word を出力する

```powershell
.venv\Scripts\python src\make_docx.py output_MeetingMinutes\<名前>\evidence_log\<名前>_議事録.md --type <会議の種類>
```

会議の種類（チェックイン / ヒアリング / その他）に応じて、固定テンプレート（[assets/](assets/)）を使う。

- **既存の Word は消さず、上書きもしない。** 同じ名前の Word があれば `<名前>_議事録_Ver2.0.docx`、`_Ver3.0` … と版を上げて保存される（2026/11/23 Aさんの指示）。

### 7. ⑦ 用語集の追加候補を抽出して知らせる

```powershell
.venv\Scripts\python src\glossary_tool.py candidates transcripts\<名前>\<名前>.json output_MeetingMinutes\<名前>\evidence_log\<名前>_議事録.md
```

- 議事録の【推定】【聞き取り不明】の語、`氏名【要確認：人名】` の名簿にない人名、文字起こしに頻出する未登録語を、用語集の「候補」シートに「未確認」で追記する。
- 用語集の Excel を記録者が開いていると保存に失敗する。その場合は閉じてもらってから再実行する。
- **追記した候補を1件ずつ見て、登録先のおすすめを「Claudeの推奨」列に書く。** `{"No.": "用語（推奨）：正式表記と意味。誤変換例「…」"}` の JSON を作って実行する。
  - 用語（推奨）：社内用語・業界用語・ツール名・プロジェクト名など、次の会議でも誤変換しそうな語。既存の行に誤変換例を足すだけでよいものはそう書く
  - 人名（推奨 / 要確認）：名簿にない人名。名簿の人の誤変換の可能性があれば書く
  - 不要：意味の取れない断片、一般語、言い回し

```powershell
.venv\Scripts\python src\glossary_tool.py recommend <おすすめの JSON>
```

- **記録者には、件数だけでなく「登録をおすすめする語」の一覧（用語・人名）を表で伝える。** 記録者が「登録先」「正式表記（確認後）」を記入したら、それを「用語」「人名」シートに反映する（記録者の指示を受けてから）。

### 8. 報告する

```powershell
.venv\Scripts\python src\timing.py <名前> show
```

次をまとめて記録者に伝える。

- 出力した Word（`output_MeetingMinutes/<名前>/<名前>_議事録[_VerN.0].docx`。会議フォルダの直下には最新の Word だけが残り、古い版は `old/` へ自動で移る。md・自己点検の結果は `evidence_log/`）
- 工程ごとの処理時間
- 【要確認】【聞き取り不明】の件数と主な箇所
- 自己点検で直した内容
- 用語集の追加候補（⑦）
- 新しく起票した Issue
