# Cloudflare 使用量分析と独自ドメイン化リサーチ

- 日付: 2026-07-11(料金は当日 Cloudflare 公式 docs で確認: [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/) / [R2 pricing](https://developers.cloudflare.com/r2/pricing/))
- 実測値ベース: R2 バケット総量・アセットサイズ・サイトの転送挙動は本日時点の production を計測

## 1. 現状の実測

| 項目 | 実測 |
|---|---|
| R2 総ストレージ | **45.49 GiB**(runs/ 37.27 + site-data/ 8.16 + build-artifacts 0.05、3,721 objects) |
| 公開 GLB | 7.8 GiB / 274 個(P50 5.6MiB、P95 146.8MiB、最大 568.3MiB) |
| サイト静的アセット | JS 235KB gz + リファレンス PNG 25.4MiB(#51 で ~2MiB へ削減予定) |
| 課金構成 | Workers Free プラン + R2(従量) |

課金の効く経路は 2 つだけ:
- **Worker 呼び出し**: `/run-assets/*`(GLB 配信)のみ。HTML/JS/画像/manifest は Workers Static Assets = **無料・無制限・クォータ非消費**
- **R2**: ストレージ + Class B(GetObject、Worker からの読み)+ Class A(アップロード/コピー/リスト)。**egress は常に $0**

## 2. アクセス量シナリオ別の月額試算

訪問者モデル: 1 人あたり平均 2 課題閲覧、遅延ロードで 1 課題 ~4 GLB 取得 → **8 Worker 呼び出し + 8 Class B/人**。

| | 100 人/日 | 1,000 人/日 | 10,000 人/日 | 100,000 人/日(バズ) |
|---|---|---|---|---|
| Worker 呼び出し/日 | 800 | 8,000 | 80,000 | 800,000 |
| Free 枠(10 万/日)内? | ✅ | ✅ | ✅(余裕 2 割) | ❌ 要 Paid |
| R2 Class B/月 | 24k | 240k | 2.4M | 24M |
| Class B 課金(10M 無料超過分 × $0.36/M) | $0 | $0 | $0 | ~$5 |
| Workers Paid($5 + 超過 $0.30/M) | — | — | — | $5 + ~$4.2 |
| ストレージ((45.5−10GB)× $0.015) | $0.53 | $0.53 | $0.53 | $0.53 |
| **月額合計** | **~$0.5** | **~$0.5** | **~$0.5** | **~$15** |

**結論: 現構成はほぼ無料で 1 万人/日までスケールし、10 万人/日のバズでも ~$15/月。** R2 の egress 無料が効いており、GLB 総転送量が課金に一切影響しないのが最大の強み。バズ時は 800,000 GLB/日で、1 取得の代表サイズを P50 の 5.6MiB とすると **~128TiB/月**、公開 GLB の単純平均 29.1MiB(7.8GiB/274)で見積もると **~667TiB/月** — どちらのモデルでも egress 課金は $0。S3+CloudFront なら同条件で数千〜数万ドル級。

### 注意点・改善余地

- **Worker Free の日次上限(10 万 req)超過時は 429**(その日の GLB 配信が止まる)。1 万人/日が見えたら **先に Workers Paid($5)へ** — 静的部分は落ちないが体験が壊れるため
- Worker の CPU 制限(Free 10ms/呼び出し)は R2→クライアントのストリーミングパススルーでは実測上問題になりにくいが、巨大 GLB で余裕を見るなら Paid(30s CPU)が安全側
- `runs/` 37GiB は生の実行成果物。月 $0.5 なので急がないが、wave 3 前に **Infrequent Access への移行 or 剪定**で削減余地あり。ただし IA は単純な半減にならない: 保管 $0.01/GB-月は Standard($0.015)より安いが、**10GB 無料枠は Standard のみ**に適用され、取り出し $0.01/GB・Class B $0.90/M・最低保管 30 日が付く。runs/ 37.27GiB を IA へ移すと残りの Standard 8.2GiB は無料枠内に収まり、IA 保管 ~$0.37/月 → 現状 ~$0.53/月から**約 3 割減**(読み出し発生時は別途課金)。runs/ はほぼ読まないアーカイブなので IA の条件には合うが、絶対額が小さいため不要成果物の剪定の方が効きやすい
- deploy 1 回あたりのコスト: R2 sync の GET ~900 + PUT 数十 → 無視できる規模

## 3. 独自ドメイン化リサーチ

参照: [Workers Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/)(2026-07-11 確認)

### 推奨: Workers Custom Domain(リダイレクトではなく直接配信)

- **前提はドメインの zone が Cloudflare 上にあること**(レジストラはどこでも OK、ネームサーバーを CF に向けるだけ。ドメイン移管は不要)
- 手順: zone 追加 → Worker の Settings > Domains & Routes > **Custom Domain** にドメイン(例 `3dgen.example.com`)を入力 → DNS レコードと証明書は **CF が全自動発行**。wrangler なら `routes = [{ pattern = "...", custom_domain = true }]`
- `workers.dev` URL は併存可(飽きたら無効化も可)
- 制約: 完全一致のみ(`example.com` に付けても `www.` は別途 Redirect Rule)、既存 CNAME と衝突不可

「リダイレクトできるか」への直接回答: **可能(Redirect Rules / Bulk Redirects)だが、その場合も zone が必要なので、どうせなら直接配信が上位互換**。SEO・共有 URL・証明書の面でも直接配信が有利。

### 副次メリット(むしろ本命級)

zone を持つと **WAF カスタムルールが解禁**される。models-merged.md の当初計画どおり、Hunyuan3D 2.1 の EU/UK/KR 遮断を **エッジ WAF + Worker 451 の二層防御**にできる(現在は Worker 層のみ)。加えて zone アナリティクス・Cache Rules・Bot 対策も使える。

### 必要なアクション(オーナー)

1. 使うドメイン名(とサブドメイン、例 `3dgen.<domain>`)を決めて教えてください
2. ドメインの zone を Cloudflare アカウントに追加し、レジストラ側でネームサーバーを CF 指定値に変更(所要 ~10 分+伝播)
3. 以降(Custom Domain 設定・WAF ルール・サイト側 URL 定数の更新)は Fable/Codex で実施可能
