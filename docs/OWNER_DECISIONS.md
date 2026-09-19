# Owner Decision Log

Jev Voice Decision は、「音声をAIへ渡して返答文を作らせる」デモではありません。

作りたかったのは、曖昧な日本語の発話を**ソフトウェアがそのまま使える小さな判断**へ変え、
その後の処理は普通のコードへ戻す構成です。

この文書では機能一覧ではなく、プロジェクトオーナーとして
**どこまでをモデルへ任せ、どこからを決定的なコードへ戻したか**
が分かる判断だけをまとめます。

---

## 1. Jevには「回答」を書かせず、「判断」だけさせた

### 課題

音声AIのデモなら、

> 音声 → LLM → 返答文

にするのが分かりやすい構成です。

ただし実際のソフトウェア内部では、
欲しいのが文章ではなく、

- これは質問か
- 返答が必要か
- 優先度はどのくらいか

という分岐材料だけ、という場面があります。

### 判断

Jevに自由文を生成させず、

- Choice
- Noul
- Score

という typed decision だけを返させました。

Jevの出力はUIへ文章として採用するのではなく、
後続コードが扱える構造化された判断として使います。

**Evidence:** [README — Jev と Python の役割分担](../README.md#jev-と-python-の役割分担) / [Phase 1](https://github.com/nikotaronosuke/jev-voice-decision/commit/0ed06101a07ac38d30f1fd4a5fb540afee993b94)

---

## 2. 「判断」と「アクション」を同じモデルへ任せなかった

### 課題

Jevが「質問」と判定したあと、

> ではどのキューへ送るか

までモデルに決めさせれば実装は短くできます。

しかしそうすると、同じ入力でもアクション規則そのものがモデル側へ隠れます。

### 判断

Jevは曖昧さを含む**認識・判断**を担当し、
実際のactionは `app/actions.py` の普通のPythonで決定するよう分けました。

例えば、

- 質問 + 返答必要 → 質問キュー
- 要望 → 要望リスト
- 感想 → フィードバック
- その他 → 記録のみ

という規則はコード側です。

「AIが全部決める」ではなく、
**曖昧な部分だけAIへ渡し、業務ルールは人が読めるコードに残す**判断です。

**Evidence:** [README — Python側の規則](../README.md#jev-と-python-の役割分担)

---

## 3. confidenceが低いとき、無理にどれかへ振り分けなかった

### 課題

Choiceには必ず最上位候補があります。

そのため最も確率の高いoptionを常に採用すれば、
すべての発話を自動分類できます。

しかし僅差や低confidenceでも強制すると、
「分からないのに決めた」結果になります。

### 判断

intent confidenceがdemo threshold未満なら、

> **判断保留 → 手動確認**

へ送ります。

abstain / reviewは失敗ではなく、
**誤った自動アクションを避けるための正常な結果**として扱っています。

**Evidence:** [README — deterministic action rules](../README.md#jev-と-python-の役割分担)

---

## 4. thresholdを「最適値」のように見せなかった

### 課題

デモで0.5のthresholdを使うと、
数字だけを見た人には

> 0.5が検証済みの最適境界

のように見える可能性があります。

### 判断

設定値はREADMEと `app/config.py` で明示的に **demo threshold** と呼びました。

精度ベンチマークで最適化した値ではありません。

画面でもaccuracyや正解率は表示せず、

- Jevの分布
- confidence
- typed decision

をそのまま見せます。

デモを評価結果のように見せない判断です。

**Evidence:** [README — demo threshold](../README.md#jev-と-python-の役割分担)

---

## 5. 音声はCloudへ送らず、STTを端末側へ置いた

### 課題

音声をそのままクラウドSTTや判断APIへ送れば構成は簡単です。

しかしこのデモでJevが必要なのは音声データではなく、
**判断対象となる文字列**です。

### 判断

音声認識は端末側の Parakeet JA で行い、
Jevへ送るのは**final transcriptだけ**にしました。

音声PCM自体はJevへ送りません。

UIにも、

> 音声は端末内で処理し、文字起こし結果だけをJevへ送信します

と明示しています。

**Evidence:** [README — Voice Mode](../README.md#2-つのモード) / [Phase 2-3](https://github.com/nikotaronosuke/jev-voice-decision/commit/75d503c4e0af91a4fe54a5f425137681fe32598d)

---

## 6. 常時聞き取りではなくpush-to-talkにした

### 課題

常時マイクを監視すれば「リアルタイムAI」らしいデモになります。

一方で、

- いつ録音しているか分かりにくい
- 不要な音声まで処理する
- 発話区間判定の責務が増える
- デモの中心であるtyped decisionから論点がずれる

という問題があります。

### 判断

Voice Modeは **録音開始 → 停止** のpush-to-talkにしました。

今回確認したかったのは常時音声監視ではなく、

> 音声 → transcript → typed decision → deterministic action

という境界だからです。

扱わない機能をあえて増やさない判断です。

**Evidence:** [README — Voice Mode](../README.md#2-つのモード)

---

## 7. partial transcriptをJevへ何度も送らず、finalを1回だけ送った

### 課題

STTのpartialを更新のたびにJevへ送れば、
判断結果もリアルタイムに変化させられます。

ただし、

- API call数が増える
- 途中の誤認識でactionが揺れる
- 同じ発話に対するdecisionが何度も発生する

という問題があります。

### 判断

このデモでは**final transcriptを1回だけJevへ送る**ことにしました。

音声認識の途中経過と、
ソフトウェアが実際に使う判断イベントを分離しています。

**Evidence:** [README — Voice Mode final transcript](../README.md#2-つのモード)

---

## 8. Jevへ送るcontextを最小にした

### 課題

判断精度を上げるために、
大量の履歴・プロフィール・過去コメントをcontextへ追加することもできます。

しかしこのデモの問いは、

> この1発話をどう分類するか

です。

### 判断

送るpayloadは、

- channel
- language
- utterance

という最小構成にしました。

音声・履歴・ユーザープロフィールなどは送りません。

モデルに与える情報を増やす前に、
**その判断に本当に必要な情報だけで成立するかを見る**方を選びました。

**Evidence:** [README — Jevへ送るもの](../README.md#jev-へ送るもの受け取るもの)

---

## 9. 音声・transcript・decision履歴を保存しなかった

### 課題

履歴をDBへ残せば、

- 後から分析できる
- セッションを再表示できる
- benchmark datasetへ転用できる

といった利点があります。

しかしデモ段階では、そこまでの保存理由がありません。

### 判断

次を永続化しません。

- 音声
- transcript
- Jev response
- API request
- session history

すべてprocess memoryだけで扱います。

STT workerへもAPI credentialを渡しません。

provider errorもraw bodyをUIへ出さず、
genericな失敗表示へ変換しています。

**Evidence:** [README — 保存しないもの](../README.md#保存しないもの)

---

## 10. RAPID DEMOでも結果を事前計算しなかった

### 課題

200件のデモを滑らかに見せるだけなら、
事前にdecision結果を保存して再生できます。

しかしそれではJevが実際に判断していることを示せません。

### 判断

RAPID DEMOは架空コメントを**実際にJevへ送信**し、
返ってきた順にUIを更新します。

結果はprecomputeせず、履歴にも保存しません。

一方で無制限並列にはせず、
concurrency上限を持ち、rate limitが来たら新規送信を止めて同時数を下げます。

「速く見せる」より、
**実APIの挙動を壊さずそのまま見せる**ことを優先しました。

**Evidence:** [RAPID DEMO commit](https://github.com/nikotaronosuke/jev-voice-decision/commit/107f4ca) / [README — RAPID DEMO](../README.md#2-つのモード)

---

## 11. このrepoではaccuracy / latency / costの勝負をしなかった

### 課題

新しいAIモデルのデモを公開すると、

- 他モデルより正確か
- 速いか
- 安いか

まで主張したくなります。

しかしこのrepoでは比較条件を固定したbenchmarkを行っていません。

### 判断

READMEで明示的に、

- 他モデルとの比較
- accuracy benchmark
- latency / cost ranking
- 「○倍速い」

を**扱わないもの**にしました。

このデモが証明するのは、

> 日本語の発話をlocal STTし、Jevのtyped decisionを普通のコードのactionへ接続できる

ところまでです。

測っていない性能を製品価値として足さない判断です。

**Evidence:** [README — このデモが扱わないこと](../README.md#このデモが扱わないこと)

---

## このプロジェクトで優先したもの

Jev Voice Decisionでは、AIらしい派手さより次を優先しています。

- 文章生成ではなくtyped decisionに限定する
- モデル判断と業務actionを分離する
- 低confidence時は自動決定しない
- demo thresholdを精度保証のように見せない
- 音声をCloudへ送らない
- 必要なときだけ録音する
- partialではなくfinal decisionを1回作る
- providerへ送るcontextを最小にする
- 履歴を必要なく保存しない
- デモ結果を事前計算しない
- 測っていないaccuracy / latency / costを主張しない

AIを使って実装していますが、
このリポジトリで重要なのはコード量ではなく、
**モデルへ任せる判断を小さく定義し、それ以外を普通のソフトウェアへ戻したこと**です。
