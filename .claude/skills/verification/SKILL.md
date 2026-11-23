---
name: verification
description: 議事録作成ツールの評価（テスト）結果を記録し、テスト結果一覧（Excel）と回ごとの報告（md）を作る。議事録を作り終えた後の評価、人手版の議事録との比較結果の記録、「テスト結果を記録して」「評価して」「前回と比べて改善した？」「テスト結果一覧を見せて」と頼まれたら使う。開発サイクルの「評価」工程で使う。
---

# 評価（テスト結果の記録）

1回の評価ごとに、**プログラムが JSON に書き出す**（正本）→ **スクリプトで Excel 一覧と md 報告を作る**。
数値は出力ファイルから機械的に集めるので、Claude が議事録や文字起こしを読み直す必要はない（コンテキストを節約する）。

```
docs/verification/
  議事録検証計画.md            評価の考え方・指標の定義（4.3）
  テスト結果一覧.xlsx          人が見る一覧（生成物。手で編集しない）
  results/<run_id>.json        1回分の結果（正本）
  reports/<run_id>.md          1回分の報告（生成物。AI が読む）
  <名前>_比較.md               人手版との詳細な比較（必要なときだけ Claude が書く）
```

run_id は `YYYYMMDD-HHMM_<名前>_<区分>`。

## 記録する項目

| 区分 | 項目 | 集め方 |
|---|---|---|
| 会議 | 会議名・種類・参加者数・音声の長さ | 会議情報ファイル、`transcripts/<名前>/<名前>.meta.json` |
| 処理時間 | ①〜⑦の工程ごとの分 | `transcripts/<名前>/<名前>.timing.json` |
| 文字起こし | セグメント数・検出話者数・補完セグメント数・話者対応表の状態 | meta.json、会議情報ファイル |
| 議事録 | 文字数・段落数・見出し数・決定事項数・TODO数・画像枠数・【推定】【聞き取り不明】【要確認】の数 | `output_MeetingMinutes/<名前>/evidence_log/<名前>_議事録.md` |
| 自己点検 | 抜けの候補・根拠のない語の候補 | `output_MeetingMinutes/<名前>/evidence_log/<名前>_議事録.check.json` |
| 用語集 | 追加候補の件数 | 用語集の「候補」シート |
| 人手版との比較 | 付け足し・確度の格上げ・無断推定・話者誤り・網羅数・キーポイント数・人手版文字数 | 人手版と比べて判定し、`--set` で入れる |
| 所見 | 気づいたこと、関連する Issue | `--note` で入れる |

人手版との比較の指標の定義は `docs/verification/議事録検証計画.md` 4.3。

## 手順

### 1. 結果を記録する（議事録の Word 出力・⑦の後）

```powershell
.venv\Scripts\python .claude\skills\verification\scripts\record_result.py <名前> --label <区分>
```

- 区分の例：`基本試行`（参加者氏名のみ）、`追加試行`（用語集など付き）、`本番`。
- 基本試行など、既定以外の議事録を評価する場合は `--minutes <ファイル名>` を付ける。
- 表示された run_id を控える。

### 2. 人手版と比べる（人手版がある場合）

- 検証では、**Word を出力し終えるまで人手版を開かない**（盲検）。
- 人手版を受け取ったら、検証計画 4.3 の指標で比べて追記する。比較の詳細が必要なら `docs/verification/<名前>_比較.md` に書く。

```powershell
.venv\Scripts\python .claude\skills\verification\scripts\record_result.py <名前> --run <run_id> --set 付け足し=0 --set 話者誤り=2 --set 網羅数=20 --set キーポイント数=22 --set 人手版文字数=10073
```

### 3. 所見を書く

気づいたことを1行ずつ。新しい論点は `issue` スキルで起票し、番号を書く。

```powershell
.venv\Scripts\python .claude\skills\verification\scripts\record_result.py <名前> --run <run_id> --note "見出しの区切りが人手版より細かい（ISSUE-021）"
```

### 4. 一覧と報告を作り直す

```powershell
.venv\Scripts\python .claude\skills\verification\scripts\build_report.py
```

- 標準出力に全回の要約（文字数・抜けの候補・話者誤り）が出る。前回との比較はこれを使う。
- `テスト結果一覧.xlsx` を開いていると保存に失敗する。

## 記録者への報告

標準出力の要約をもとに、前回（同じ会議・前の区分）から何が改善し、何が悪化したかを表で伝える。Excel のパス（`docs/verification/テスト結果一覧.xlsx`）も添える。
