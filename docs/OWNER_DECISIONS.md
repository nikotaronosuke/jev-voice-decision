# Owner Decision Log

日本語 | [English](OWNER_DECISIONS.en.md)

Jev Voice Decision で残す判断は3つです。READMEの仕様を言い換えるのではなく、モデルへ任せる範囲を決めたものだけに絞ります。

## 1. 「返答文生成」ではなく typed decision に限定した

最初から音声 → LLM → 返答文というデモにはせず、

- intent: Choice
- needs_response: Noul
- priority: Score

だけを Jev に任せました。

その後の「質問キューへ入れる / 要望へ送る / 記録のみ」は普通の Python で決定します。

曖昧さをモデルへ、業務ルールを deterministic code へ分離した判断です。

**Evidence:** [Phase 1](https://github.com/nikotaronosuke/jev-voice-decision/commit/0ed06101a07ac38d30f1fd4a5fb540afee993b94)

## 2. confidence が低いときは分類を強制しなかった

Choice は必ず最上位候補を返せますが、低confidenceでも採用すると「分からないのに決める」動きになります。

そこで demo threshold 未満は **判断保留 → 手動確認** にしました。

threshold 自体も「最適化済み」とは扱わず、READMEで demo threshold と明記しています。

**Evidence:** current implementation / README

## 3. Rapid Demo を事前計算せず、実API + bounded concurrency にした

200件を滑らかに見せるだけなら結果を事前生成できますが、それでは実APIデモではありません。

実際に Jev へ送り、返った順に表示。rate limit が来た場合は新規送信を止め、同時数を下げるようにしました。

「速く見せる」より、実際のprovider挙動をそのまま見せる方を選びました。

**Evidence:** [Rapid Demo](https://github.com/nikotaronosuke/jev-voice-decision/commit/107f4ca)
