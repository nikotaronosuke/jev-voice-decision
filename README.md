# Jev Voice Decision

日本語の音声を文字起こしし、Jevで“回答生成ではなく判断”を行うリアルタイムデモ。

音声 → テキスト → 判断 → アクション、という流れを一画面で見せます。
音声認識（STT）は端末内で行い、判断は TypeSafe の System One モデル **Jev** が担当します。
Jev は文章を生成しません。曖昧な日本語の発話を、コードがそのまま分岐に使える
typed decision（Choice / Noul / Score）に変えます。

## 何が起きるか

```
🎙 INPUT   「これってどうやって使うんですか？」   （マイク、または文字入力）
   ↓
📝 TRANSCRIPT   これってどうやって使うんですか？   （端末内の Parakeet JA）
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
| 音声を文字にする | 端末内の STT（NVIDIA Parakeet JA、NeMo） | `app/stt/` |
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

## 2 つのモード

- **TEXT**: 日本語を入力して「判断する」。Demo examples をクリックすると入力欄に入ります（自動送信はしません）。
- **RAPID DEMO**（TEXT 内のボタン）: 架空の日本語コメント 200 件（`fixtures/rapid-demo-200.json`）を Jev へ送り、typed decision とアクションが返ってきた順に次々切り替わる様子を確認できます。同時に送るのは最大 `RAPID_CONCURRENCY` 件（既定 12）で、rate limit の応答があれば新規送信を一時停止して同時数を下げます。結果は事前計算せず、履歴にも残しません。
- **VOICE**: 「録音開始」で話し、「停止」で文字起こしと判断に進みます（push-to-talk。常時聞き取りはしません）。
  画面は 待機中 → 聞き取り中 → 文字起こし中 → Jev が判断中 → 完了 の順に切り替わり、
  処理中のカードだけが強調されます。文字起こしは final transcript を 1 回だけ Jev に送ります。

Voice Mode では画面下に「音声は端末内で処理し、文字起こし結果だけをJevへ送信します」と表示します。

## Jev へ送るもの・受け取るもの

送るのは final transcript と、判断に必要な最小の文脈だけです。

```json
{"channel": "live_stream_comment", "language": "ja", "utterance": "<文字起こし結果>"}
```

音声そのものは送りません。受け取るのは上の表の typed decision と、model 名・token 数・request id です。

## 使い方

必要なもの: Windows、Python 3.10 以上、TypeSafe の API キー。
Voice Mode にはさらに WSL（Ubuntu）上の NeMo 環境と Parakeet JA のチェックポイント、NVIDIA GPU（無い場合は CPU）が必要です。

```
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
```

設定は環境変数、または `.env.example` を `.env` にコピーして書きます（`.env` は Git 管理外）。

| 変数 | 用途 |
| --- | --- |
| `TYPESAFE_API_KEY` | Jev の API キー（必須） |
| `JVD_PARAKEET_WSL_PYTHON` | NeMo と torch が入った WSL 側 venv の python のパス（Voice Mode） |
| `JVD_PARAKEET_MODEL_DIR` | Parakeet JA の `*.nemo` を 1 つ置いたフォルダーの WSL 側パス（Voice Mode） |
| `JVD_PARAKEET_EXTRACTED_DIR` | 展開済みチェックポイントのフォルダー（任意。読み取りのみ） |

```
.\scripts\run.ps1                                        # デスクトップアプリを起動
.venv\Scripts\python.exe -m pytest                       # ユニットテスト（TypeSafe へも WSL へも通信しない）
.venv\Scripts\python.exe scripts\smoke_jev.py --confirm-send   # 架空の 6 文で実 API を 1 回ずつ呼ぶ
.venv\Scripts\python.exe scripts\privacy_scan.py         # commit 前のスキャン
```

Voice Mode の STT worker はアプリ起動時にバックグラウンドで立ち上がります。
モデルの読み込みが終わるまで「録音開始」は押せません（初回は数分かかることがあります）。

## 保存しないもの

音声、文字起こし、Jev のレスポンス、API リクエスト、セッション履歴。
すべて現在のプロセスのメモリにだけあり、アプリを終了すると消えます。
マイクの音声は 16 kHz の PCM としてメモリ上で扱い、文字起こし後に捨てます。
STT worker には資格情報を含む環境変数を一切渡しません。
API キーはコードにも UI にもログにも出しません。エラー時は provider の応答本文を表示せず、
「Jevから判断を取得できませんでした」とだけ出します。自動リトライは最大 1 回です。

## 構成

```
app/
  main.py               … pywebview のウィンドウと、ページへ公開する小さな API
  config.py             … demo threshold と Voice Mode の設定（API キーは読まない）
  models.py             … typed decision と結果の dataclass
  pipeline.py           … テキスト / 音声 → Jev → 判断 → アクション。履歴はメモリのみ
  actions.py            … 決定的なアクション規則（Python）
  jev/questions.py      … Jev への 3 つの質問（人が読んで直せる定数）
  jev/client.py         … typesafe-sdk の薄い adapter とエラーの安全化
  stt/microphone.py     … WASAPI マイク取得（メモリ上の PCM16 16 kHz）
  stt/audio.py          … 因果的な resampler と PCM 変換
  stt/parakeet_worker.py… WSL 側で動く NeMo worker（stdio の JSONL、ネットワーク不使用）
  stt/parakeet.py       … Windows 側のドライバ（起動・文字起こし・終了）
  ui/                   … HTML / CSS / JavaScript（ビルド不要）
fixtures/demo-comments.json … 架空のデモ用コメント
tests/                  … fake transport / fake worker によるユニットテスト
scripts/                … 起動、実 API smoke、privacy scan
```

## このデモが扱わないこと

他モデルとの比較、accuracy benchmark、latency / cost のランキング、
「○倍速い」といった性能主張、チャット bot、回答文の生成、RAG、ログイン、DB、モバイル版、常時聞き取り。

## ライセンス

MIT License（[LICENSE](LICENSE) を参照）。
