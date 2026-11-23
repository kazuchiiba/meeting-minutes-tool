# meeting-minutes-tool（議事録作成ツール）

会議の録音から、**人手で書いた議事録と同じ書式の Word 議事録を、事実に忠実に作る**ツールです。
文字起こし・話者分離はすべてローカルの PC で行い、**会議の音声を外部のサービスに送りません**。
議事録の文章を書く工程だけ Claude（Claude Code）を使い、そこでは文字起こしのテキストだけを渡します。

## 処理の流れ

```
input/<名前>.m4a（録音）＋ input/<名前>.会議情報.txt（会議名・参加者など）
   │ ① 文字起こし        src/transcribe.py   faster-whisper large-v3-turbo（CPU）
   │ ② 話者分離（任意）  src/diarize.py      pyannote 3.1（CPU）。ON/OFF を設定で切り替える
   │ ③ 抜けの補完        src/fill_gaps.py    Whisper が取りこぼした発言を探し直す
   ▼                     （①〜③は src/run_pipeline.py でまとめて実行する）
transcripts/<名前>/<名前>.speakers.txt
   │ ④ 議事録の作成      Claude Code の minutes スキル（書き方のルールは .claude/skills/minutes/references/）
   │ ⑤ 自己点検          src/check_coverage.py   抜け・根拠のない語の候補を出し、④に戻って直す
   │ ⑥ Word 出力         src/make_docx.py        固定テンプレート（.claude/skills/minutes/assets/）
   │ ⑦ 用語集の追加候補   src/glossary_tool.py
   ▼
output_MeetingMinutes/<名前>/<名前>_議事録[_VerN.0].docx（記録者が確認・修正して最終版にする）
```

`<名前>` は音声ファイル名（拡張子なし）です。会議ごとにフォルダを分けます。

## 必要なもの

| 項目 | 内容 |
|---|---|
| OS | Windows 11（検証環境）。GPU は不要 |
| Python | 3.12 |
| ディスク | モデル約1.7GB ＋ Python 環境2つで約3GB |
| アカウント | Hugging Face（pyannote の利用規約への同意とトークン。話者分離を使う場合）、Claude Code（④） |
| ネットワーク | 初回のモデルのダウンロードと、④での Claude との通信のみ |

## 環境の作り方

faster-whisper と pyannote は依存ライブラリのバージョンが衝突するため、Python 環境を2つに分けます。

```powershell
# 1. 文字起こしなど用（.venv）
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements-whisper.txt

# 2. 話者分離用（.venv-diar）。torch は CPU 版の配布元を指定する
py -3.12 -m venv .venv-diar
.venv-diar\Scripts\python -m pip install --upgrade pip
.venv-diar\Scripts\python -m pip install -r requirements-diar.txt --extra-index-url https://download.pytorch.org/whl/cpu

# 3. Hugging Face の準備（話者分離を使う場合、初回のみ）
#    (a) https://huggingface.co/pyannote/speaker-diarization-3.1 と
#        https://huggingface.co/pyannote/segmentation-3.0 で利用規約に同意する
#    (b) https://huggingface.co/settings/tokens で Read 権限のトークンを作る
#    (c) トークンを保存する
.venv-diar\Scripts\python -c "from huggingface_hub import login; login()"
```

- モデルは初回の実行時に自動でダウンロードされます。
- 日本語を含むパスで動かすため、スクリプトを直接実行するときは `PYTHONUTF8=1` を設定します（`run_pipeline.py` は自動で設定します）。
- 用語集（`docs/design/議事録作成用の用語集.xlsx`）は社内の情報を含むため、このリポジトリには入っていません。用語・人名・候補シートを持つ Excel を各自で用意します（なくても動きますが、誤変換の補正と自己点検が弱くなります）。

## 設定のしかた

### 1. 処理のパラメータ：`setting/setting.xlsx`

黄色の「設定値」の列だけを変えます。空欄なら既定値で動きます。

| シート | 項目 | 既定値 | 内容 |
|---|---|---|---|
| 文字起こし | Whisper に用語集を渡す | 渡す | 参加者名と用語集の語を Whisper に渡し、誤変換を減らす |
| 文字起こし | 渡す語の上限（文字数） | 120 | Whisper に渡せる長さには上限がある |
| 話者分離 | 話者分離（pyannote）を行う | **しない** | ②を行うか（下の目安を参照） |
| 話者分離 | 窓のずらし幅（秒） | 1.0 | 大きいほど速い。2.0 で約2倍速・精度の落ち約2%。3.0 以上は精度が大きく落ちる |
| 話者分離 | 1話者あたりの最低特徴量数 | 自動 | ずらし幅に合わせて自動で決まる |

### 2. 会議ごとの情報：`input/<名前>.会議情報.txt`

議事録を作る前に記録者が書きます。ひな形は次のコマンドで作れます。

```powershell
.venv\Scripts\python src\meeting_info.py init input\<名前>.m4a --participants 氏名,氏名 --recorder 氏名
.venv\Scripts\python src\meeting_info.py show input\<名前>.m4a     # 内容と、話者分離を行うかの判定を表示
```

```
会議名: 定例会
日時: 2026/11/20(金)
会議の種類: ヒアリング            ← チェックイン / ヒアリング / その他（Word のテンプレートが変わる）
記録者: 氏名
参加者: 氏名、氏名、氏名
話者分離: する                    ← 空欄なら setting.xlsx の設定。この会議だけ変えるときに「する / しない」
Whisperに用語集を渡す:            ← 空欄なら setting.xlsx の設定
Whisperに渡す追加の語: 固有名詞、…

[話者対応表]                      ← 話者分離する場合。SPEAKER_00: 氏名 の形で1行ずつ
SPEAKER_00: 氏名
```

### 3. 話者分離（pyannote）を使うかの目安

社内の会議で、同じ文字起こしから議事録を作り、人手版と発言者を照合した結果です。

| 会議の性質 | pyannote なし（Claude が内容から推定） | pyannote あり＋人が確かめた話者対応表 | 目安 |
|---|---|---|---|
| ヒアリングのように自由に発言し、質問する人が複数いる会議 | 話者誤り 約21% | 話者誤り 約2% | **「する」にする**。話者対応表は人が確かめる |
| 司会が順に指名する会議（チェックインなど） | 話者誤り 0件 | 話者誤り 0件 | 「しない」でよい |

- 話者対応表を AI の推定だけで作ると、1か所の取り違えで1人分の発言がすべて誤ります（約20%）。pyannote を使うときは、冒頭を聞いて対応表を確かめてください。
- 話者分離は CPU で音声の約1.9倍の時間がかかります（「しない」なら①③だけで、音声の約1倍）。

## 実行のしかた

### ①〜③ 文字起こし・話者分離・抜けの補完

```powershell
.venv\Scripts\python src\run_pipeline.py input\<名前>.m4a --speakers <参加人数> > logs\run_<名前>.log
```

- 時間がかかる（CPU で音声の1〜3倍）ので、終わるまで PC をスリープさせないでください（実行中は自動でスリープを抑止しますが、蓋を閉じた時の動作は電源設定に従います）。
- Teams・Notion の文字起こし（`.vtt` / `.docx` / `.txt` / `.md`）を同じ名前で `input/` に置くと、その話者名を使います（話者分離は不要）。
- 結果は `transcripts/<名前>/`、工程ごとの処理時間は `transcripts/<名前>/<名前>.timing.json`。

### ④〜⑦ 議事録の作成〜Word 出力

このフォルダで Claude Code を起動し、「`input/<名前>.m4a` から議事録を作って」と頼みます（`minutes` スキルが手順どおりに進めます）。手で実行する場合は次のとおりです。

```powershell
# ⑤ 自己点検（④で書いた md に対して）
.venv\Scripts\python src\check_coverage.py transcripts\<名前>\<名前>.json output_MeetingMinutes\<名前>\evidence_log\<名前>_議事録.md
# ⑥ Word 出力
.venv\Scripts\python src\make_docx.py output_MeetingMinutes\<名前>\evidence_log\<名前>_議事録.md --type ヒアリング
# ⑦ 用語集の追加候補
.venv\Scripts\python src\glossary_tool.py candidates transcripts\<名前>\<名前>.json output_MeetingMinutes\<名前>\evidence_log\<名前>_議事録.md
```

- Word は上書きしません。同じ名前があれば `_Ver2.0`、`_Ver3.0` … と版を上げて保存し、古い版は `old/` へ移します。
- 【推定】【聞き取り不明】【要確認】は黄色の蛍光ペンで示します。記録者が確認・修正して最終版にしてください。

## フォルダ構成

```
input/                         録音・会議情報ファイル・人手版（リポジトリには入れない）
transcripts/<名前>/            ①〜③の出力（リポジトリには入れない）
output_MeetingMinutes/<名前>/  議事録（リポジトリには入れない）
  <名前>_議事録[_VerN.0].docx   最新の Word だけを置く
  old/                         古い Word（自動で移す）
  evidence_log/                議事録の md・自己点検の結果など
logs/                          実行ログ（リポジトリには入れない）
setting/setting.xlsx           処理のパラメータ
src/                           ツールのコード
.claude/skills/                Claude Code のスキル（minutes：議事録作成、dev-cycle・issue・verification など：開発用）
docs/                          設計書・Issue・検証結果
tools/export_public.py         このリポジトリに上げる公開用コピーを作るスクリプト
```

## 守ること・注意

- **会議の音声・動画をクラウドサービスや外部 API に送らないでください。**
- `.claude/settings.json` は、親フォルダにある音声アップロード防止のフック（`../.claude/hooks/block-audio-upload.ps1`）を呼びます。このリポジトリだけを取り出して使う場合は、フックを用意するか、設定から外してください。
- ファイルは削除せず、片付けは移動で行います（`src/paths.py` の `move_into`）。
- 議事録は AI の下書きです。最終版にする前に、必ず人が確認してください。

## このリポジトリについて

- 社内の検証で作ったツールの公開用コピーです。会議のデータ（音声・文字起こし・議事録・用語集・ログ）は含みません。
- ドキュメント中の人名・社名・部署名は、記号（A、B…、当社、取引先P など）に置き換えています。
- 公開用コピーは `tools/export_public.py` で作ります（置き換え表は別に管理し、リポジトリには入れません）。
