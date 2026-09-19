# Jev Voice Decision

日本語の音声を文字起こしし、Jevで“回答生成ではなく判断”を行うリアルタイムデモ。

音声 → テキスト → 判断 → アクション、という流れを一画面で見せます。
音声認識（STT）は端末内で行い、判断は TypeSafe の System One モデル **Jev** が担当します。
Jev は文章を生成しません。曖昧な日本語の発話を、コードがそのまま分岐に使える
typed decision（Choice / Noul / Score）に変えます。

> 現在の状態: **Phase 1（Text Mode）を実装済み**。Voice Mode（Phase 2 以降）は未実装です。

## 何が起きるか

```
🎙 INPUT   「これってどうやって使うんですか？」
   ↓
📝 TRANSCRIPT   これってどうやって使うんですか？
   ↓
🧠 JEV DECISIONS
   主な意図      質問 ████████████  感想 ██  要望 █  その他 █   （Choice）
   返答が必要？  YES ███████████  NO ██                        （Noul）
   優先度        低 ──────────●──── 高                          （Score）
   ↓
⚡ ACTION   質問 → 質問キューへ            （Python の規則で決定）
```

題材は完全に架空のライブ配信・イベントのコメントです。実在の配信・人物・発言とは無関係です。

## Jev と Python の役割分担

| 役割 | 担当 | 場所 |
| --- | --- | --- |
| 曖昧な発話を typed decision に変える（確率つき） | Jev | `app/jev/questions.py`（質問の定義）、`app/jev/client.py`（SDK の薄い adapter） |
| どのアクションに振り分けるかを決める（決定的） | 普通の Python | `app/actions.py` |

Jev に投げる質問は 3 つで、1 回の API 呼び出しにまとめています。

| 名前 | primitive | 問い | 返るもの |
| --- | --- | --- | --- |
| `intent` | Choice | 主な意図はどれか（質問 / 感想 / 要望 / その他） | 選ばれた option、全 option の確率分布、confidence |
| `needs_response` | Noul | この発話には返答が必要か | 「はい」である確率（0〜1） |
| `priority` | Score | 対応の優先度はどの段階か（4 段階の状況記述） | 確率加重の score（0〜3）、各段階の確率分布、confidence、legend |

Python 側の規則（`app/actions.py`）:

- 主な意図の confidence が demo threshold（0.5）未満 → **判断保留** → 手動確認
- 質問 かつ 返答が必要 → 質問キューへ
- 質問 だが 返答は不要 → 記録のみ
- 要望 → 要望リストへ
- 感想 → フィードバックへ
- その他 → 記録のみ
- 優先度 score が 2.0 以上 → UI で強調

閾値はすべて `app/config.py` に **demo threshold** として明示してあります。最適化した値ではありません。
画面に出すのは「Jevの出力分布」と「confidence」で、精度や正解率は表示しません。

## Jev へ送るもの・受け取るもの

送るのは final transcript と、判断に必要な最小の文脈だけです。

```json
{"channel": "live_stream_comment", "language": "ja", "utterance": "<文字起こし結果>"}
```

音声そのものは送りません。受け取るのは上の表の typed decision と、model 名・token 数・request id です。

## 使い方

必要なもの: Windows、Python 3.10 以上、TypeSafe の API キー。

```
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
```

API キーは環境変数 `TYPESAFE_API_KEY` に設定します（`.env.example` を `.env` にコピーして書く方法も可。`.env` は Git 管理外）。

```
.\scripts\run.ps1                                        # デスクトップアプリを起動（Text Mode）
.venv\Scripts\python.exe -m pytest                       # ユニットテスト（TypeSafe へは通信しない）
.venv\Scripts\python.exe scripts\smoke_jev.py --confirm-send   # 架空の 6 文で実 API を 1 回ずつ呼ぶ
.venv\Scripts\python.exe scripts\privacy_scan.py         # commit 前のスキャン
```

## 保存しないもの

音声、文字起こし、Jev のレスポンス、API リクエスト、セッション履歴。
すべて現在のプロセスのメモリにだけあり、アプリを終了すると消えます。
API キーはコードにも UI にもログにも出しません。エラー時は provider の応答本文を表示せず、
「Jevから判断を取得できませんでした」とだけ出します。自動リトライは最大 1 回です。

## 構成

```
app/
  main.py          … pywebview のウィンドウと、ページへ公開する小さな API
  config.py        … demo threshold などの設定（API キーは読まない）
  models.py        … typed decision と結果の dataclass
  pipeline.py      … テキスト → Jev → 判断 → アクション。履歴はメモリのみ
  actions.py       … 決定的なアクション規則（Python）
  jev/questions.py … Jev への 3 つの質問（人が読んで直せる定数）
  jev/client.py    … typesafe-sdk の薄い adapter とエラーの安全化
  stt/             … Text Mode（Phase 2 で端末内 STT を追加予定）
  ui/              … HTML / CSS / JavaScript（ビルド不要）
fixtures/demo-comments.json … 架空のデモ用コメント
tests/             … fake transport によるユニットテスト
scripts/           … 起動、実 API smoke、privacy scan
```

## このデモが扱わないこと

他モデルとの比較、accuracy benchmark、latency / cost のランキング、
「○倍速い」といった性能主張、チャット bot、回答文の生成、RAG、ログイン、DB、モバイル版。

## ライセンス

未定（公開時に決めます）。
