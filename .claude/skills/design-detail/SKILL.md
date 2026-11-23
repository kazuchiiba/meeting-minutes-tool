---
name: design-detail
description: 議事録作成ツールのコード（src/*.py）ごとの詳細設計書を docs/design/design_detail/ に作成・更新する。コードが変わったファイルだけを書き直す。「詳細設計書を作って」「詳細設計を更新して」と頼まれたら使う。開発サイクルの最後（実装と評価が終わった後）に使う。
---

# 詳細設計書の作成・更新

`src/*.py` の1ファイルにつき1つ、`docs/design/design_detail/<ファイル名>.md` を書く。
詳細設計書は **AI が読むもの**（人が読む版はツール説明書の HTML に取り込まれる）。

## 手順

### 1. 書き直しが必要なファイルを調べる

```powershell
.venv\Scripts\python .claude\skills\design-detail\scripts\stale.py
```

- 「未作成」「要更新」のファイルだけを書く。「最新」は読まない・書かない（コンテキストと時間の節約）。
- 「元のコードなし」は、コードが削除・改名された詳細設計書。記録者に伝えて削除するか確認する。

### 2. 1ファイルずつ書く

対象のコードを読み、[assets/template.md](assets/template.md) の章立てで書く。

- **1行目**は次のコマンドの出力をそのまま入れる（これで「最新」と判定される）。

```powershell
.venv\Scripts\python .claude\skills\design-detail\scripts\stale.py --header src\<ファイル名>.py
```

- 書き方
  - コードに書いてあることだけを書く。推測で仕様を足さない。
  - 「設定値とその理由」「エラーと注意点」は、コードのコメント、`docs/design/議事録作成ツール設計書.md`、関連 Issue から理由を拾う。理由が見つからなければ「理由の記録なし」と書く。
  - 全体の設計（工程のつながり・環境構築）は設計書に任せ、詳細設計書はそのファイルの中身に絞る。
  - 表を中心に、短く書く。

### 3. 確かめる

```powershell
.venv\Scripts\python .claude\skills\design-detail\scripts\stale.py
```

すべて「最新」になったことを確かめる。

### 4. 報告する

書き直したファイルの一覧と、書く途中で見つけたコードの問題（未使用の変数、設計書との食い違いなど）を記録者に伝える。問題は `issue` スキルで起票する。
