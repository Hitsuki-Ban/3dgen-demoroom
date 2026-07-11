# アーキテクチャと運用

README から分離した、仕組み・再現性・コストの詳細。閲覧者向けの要点は [README](../README.md) を参照。

## パイプライン

```
tasks/(25課題・リファレンス画像)
  └→ models/<model>/(ピン留め Docker)── RunPod レンタル GPU で実行
        └→ 成果物 + meta.json を R2 へ逐次アップロード(タスク単位)
              └→ GitHub Actions(deploy.yml)で R2 同期 → ビルド → Cloudflare Workers 配信
                    (GLB は Worker の /run-assets/* ルートで R2 から直接ストリーミング)
```

- ベンチ実行は失敗に強い構成: タスクごとの逐次アップロードにより、Pod が途中で落ちても完了分の成果物と `failure.json` は必ず残る
- 起動 watchdog(SSH 到達性)・起動テレメトリ(`runpod-startup.json`)・残高ガードで、課金事故を多層防御
- RunPod の所有権は R2 の強整合な owner object を `launcher -> handoff_pending -> runtime` と `If-Match` CAS し、container runtime の ACK を待って引き継ぐ。timeout/ACK/cleanup の競合も CAS で一人の owner に決着し、RunPod GraphQL の `terminateAfter` を process crash・通信断の hard deadline とする。model runner は Pod を削除せず、task 成果物・`failure.json` は task 単位の staged publish だけで公開する。runtime は SSH/handoff/model の前に旧 terminal status を status-only `starting` PUT で置き換え、runner log を空にする。その後は分離した `/work/runpod-telemetry` のログと `finalizing` status だけを sweep し、単一 status object を terminal `ok`/`failed` にしてから cleanup/DELETE を行う。確定済み runtime owner は cleanup marker の R2 障害時も DELETE を試みるが、不確定な launcher は DELETE を競合させない

## ビューア(web/)

- Three.js。**単一 WebGL コンテキスト**のシザービューポートで最大 11 モデルを同時レンダリング(コンテキスト数制限の回避と省メモリ)
- カメラ同期つき比較、表示モード切替(PBR / ワイヤーフレーム / matcap / 法線 / UV チェッカー)
- 本番 URL は `https://3dgen.hitsuki.space`。Worker の Custom Domain は [web/wrangler.jsonc](../web/wrangler.jsonc)、zone の WAF / apex redirect は [infra/cloudflare/hitsuki-space/](../infra/cloudflare/hitsuki-space/) を source of truth とする
- Hunyuan3D 2.1 の地域制限(EU / 英国 / 韓国)は、zone WAF が対象パスを入口で Block し、Worker も HTTP 451 を返す二層構成。UI はライセンス解説プレースホルダを表示する([web/src/worker.ts](../web/src/worker.ts))

## 再現性

- 各モデルはコード commit / 重み revision をピン留めした Docker イメージで実行。イメージ digest は [docs/runs/](runs/) の実行レポートに記録
- メタデータ契約は [bench/src/bench_harness/meta.py](../bench/src/bench_harness/meta.py)(REQUIRED_META_KEYS)。全 `meta.json` を成果物と同じ場所で公開
- 新規 VRAM 値は GPU UUID と測定 scope を `vram_measurement` に記録する。Linux の inference process group は同時刻の process 使用量を合算し、RunPod は公式の GPU 独占保証に基づく selected-device total と baseline を明示する。フィールドがない既存値は `legacy_device_total` であり、新口径と同一とは扱わない([詳細契約](../bench/README.md#vram-measurement-contract))
- 決定的な生成になるモデルでは、独立した 2 回の実行でバイト一致の GLB を確認済み
- 取得時点のライセンス原文を成果物に同梱(`LICENSES.txt`)
- 非商用ライセンスの補助重み(背景除去モデル等)を含む Docker イメージは非公開(GHCR private)

## コスト

レンタル GPU 総支出は **約 $21**(2026-07-11、全 11 モデル × 25 課題の publish 完了まで。失敗試行・ステージング・スモークテスト・設定不変の上位 GPU retry 込み。TripoSR はローカル GPU 実行で $0)。実行ごとの内訳・GPU 単価・失敗の記録は [docs/runs/](runs/) を参照。

## リポジトリ構成

| パス | 内容 |
|---|---|
| [`tasks/`](../tasks/) | 25 課題の定義とリファレンス画像 |
| [`models/`](../models/) | モデルごとの Dockerfile / runner(ピン留め済み) |
| [`bench/`](../bench/) | 実行ハーネス(uv / Python)。タスク検証・メタデータ契約・RunPod 起動・R2 アップロード |
| [`web/`](../web/) | 展示サイト(Vite + React + Three.js + Tailwind) |
| [`infra/cloudflare/`](../infra/cloudflare/) | Custom Domain 周辺の Cloudflare zone 構成(Terraform) |
| [`docs/design/`](design/) | ベンチマーク設計・実行プロトコル |
| [`docs/research/`](research/) | モデル選定・GPU レンタル・ホスティングの調査記録(二重調査の突き合わせ形式) |
| [`docs/runs/`](runs/) | クラウド実行レポート(コスト・イメージ digest・失敗の記録) |

## 運営

このリポジトリは AI エージェント 2 体(Fable / Codex)+人間オーナー 1 名で運営。分担・レビュー体制・ローカル検証ポリシーは [AGENTS.md](../AGENTS.md)。
