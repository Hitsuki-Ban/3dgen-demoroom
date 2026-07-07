# レンタルGPU 突き合わせ結論(merged)

- 確定日: 2026-07-08
- 元資料: `gpu-rental-fable.md` / `gpu-rental-codex.md`(独立調査、2026-07-07)
- 本ドキュメントが設計判断の根拠。以後の変更は PR で行う

## 両調査の一致点(そのまま採用)

- **本命: RunPod Pods(on-demand, Secure Cloud 優先)** — 4090/5090/A100/H100/L40S を単一アカウント・同一 API で扱え、Docker 完全制御、秒課金、egress 明示無料、`runpodctl`/Python SDK/REST が成熟
- **最安代替: Vast.ai** — ただし最終ベンチは `verified=true` + on-demand + 高 reliability + direct port + egress 単価確認を条件に固定
- **Modal**: Dockerfile 化が安定した後のジョブ並列基盤としては優秀。consumer GPU がなく単価も高いので初期には使わない
- **Lambda**: A100/H100 の VM デバッグ用 fallback。**Colab は不採用**(Docker/API 不可)
- **Replicate / fal.ai**: ホスト済みモデルの sanity check 専用。ベンチ基盤にはしない(バージョン・ハード・設定を制御できない)

## GPU 戦略の決定

**基準環境は RTX 5090 (32GB) を目標にしつつ、Codex 案の「段階ゲート方式」を採用する:**

1. **Gate 1**: 軽量モデル(TripoSR / TripoSG 級)で CUDA 12.8 + torch 2.7+ のベースラインイメージを確立(ローカル 4070 Ti で先行検証)
2. **Gate 2**: nvdiffrast / flash-attn / spconv 依存の重いモデルで extension smoke test(1 prompt 生成まで)を通す
3. **Gate 3**: 32GB を超える・5090 で extension が通らないモデルは 4090(古スタック互換)または A100 80GB fallback へ振り、その旨をメタデータとサイト表示に明記

**速度比較は GPU 種が同じもの同士でのみ行う**(Codex 提案)。attention backend・precision もログに残し、異種 GPU 間の生成時間は参考値扱いにする。

### sm_120(Blackwell)互換の必須対策(Codex 調査より採用)

- イメージは CUDA 12.8+ / `torch>=2.7` cu128 wheel を明示
- 自前 CUDA extension は `TORCH_CUDA_ARCH_LIST="8.9 12.0"`(ローカル 4070 Ti・4090・5090 共用)
- flash-attn は SDPA fallback で先に動かし、検証済み wheel がある場合のみ有効化
- 必須ログ: `torch.__version__` / `torch.version.cuda` / `torch.cuda.get_arch_list()` / driver / attention backend / extension のビルド元 / peak VRAM

## 費用見込み(両調査の統合)

- 素の GPU 時間: 13.3〜34.7h(8 モデル × 20 課題 + セットアップ 8h)。リトライ等で +20〜50%
- **consumer GPU 統一時の素の GPU 代: $4〜35**(Vast.ai 5090 median $0.47/h 〜 RunPod 5090 $0.99/h)
- A100/H100 fallback を数モデルで使っても総額 **$50 以内**が現実ライン。初回入金は $50 で十分
- ローカル 4070 Ti での事前検証(AGENTS.md 参照)により、リモートのセットアップ・デバッグ時間は見積の 8h からさらに圧縮できる見込み

## 運用ルール(Codex 案を採用)

- 成果物パスは GPU 種を含める: `runs/{model}/{gpu}/{timestamp}/`
- R2 への upload をジョブ終了条件にする(GPU volume を唯一の保管場所にしない)
- marketplace 利用時は host id を公開資料に載せず、GPU 種 / 価格 / verified / region / driver だけ記録
- RunPod は `gpuTypeIds` + `allowedCudaVersions`(5090 は 12.8+)+ `networkVolumeId` を API 指定
- コンテナは自己終了パターン(`RUNPOD_POD_ID` + scoped key)で GitHub Actions の 6h 制限を回避

## オーナー作業(確定版)

1. https://www.runpod.io アカウント作成 → Billing で $50 入金(日本発行カード可、Stripe 経由)
2. 支出上限をデフォルト $80/hr から $5〜10/hr に引き下げ
3. API キー発行(一度しか表示されない)→ リポジトリ secrets `RUNPOD_API_KEY` に登録
4. (Vast.ai は価格メリットが必要になった段階で追加。初期は RunPod のみでよい)
