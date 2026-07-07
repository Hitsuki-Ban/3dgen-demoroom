# ベンチ対象モデル 突き合わせ結論(merged)

- 確定日: 2026-07-08(同日改訂: オーナー決定により Hunyuan3D 2.1 を geo 制限付き採用に変更)
- 元資料: `models-fable.md` / `models-codex.md`(独立調査、2026-07-07)
- 相違点は独立検証エージェントが一次ソース(GitHub / HF / arXiv / LICENSE 原文)で確認済み(2026-07-08)
- 本ドキュメントが設計判断の根拠。以後の変更は PR で行う

## 確定ラインナップ v1(11 モデル)

| # | モデル | 入力 | 出力 | ライセンス(コード/重み) | VRAM 目安 | 選定理由 |
|---|---|---|---|---|---|---|
| 1 | **TRELLIS.2-4B** (Microsoft) | image | PBR mesh | MIT / MIT | ≥24GB | 2026 年時点の完全オープン SOTA 基準線 |
| 2 | **Pixal3D** (TencentARC) | image | textured GLB | MIT / MIT | 標準 1536、low-VRAM 1024 モードあり(実測要) | SIGGRAPH 2026。TRELLIS.2 バックボーン+ピクセル整合で原画像忠実度特化。flash-attn はソフト依存(SDPA fallback) |
| 3 | **TripoSG** (VAST-AI) | image | mesh(テクスチャなし) | MIT / MIT | ~8GB | ジオメトリ品質枠。ローカル 4070 Ti で検証可 |
| 4 | **Direct3D-S2** (DreamTech) | image | 高解像度 mesh | MIT / MIT | 512: ~10GB / 1024: ~24GB | 最高ボクセル解像度枠。torchsparse ビルドに注意 |
| 5 | **Step1X-3D** (StepFun) | image | textured GLB | Apache-2.0 / Apache-2.0 | ~27–29GB | 最クリーンなライセンスで geometry+texture 実用枠 |
| 6 | **PartCrafter** | image | パーツ分離 mesh | MIT / MIT | ≥8GB | パーツ分離生成 — ゲームアセット制作に直結する差別化枠 |
| 7 | **TRELLIS v1** (Microsoft) | text / image | mesh / **3DGS** / RF | MIT / MIT | ~16GB | text-to-3D 軸 + 3DGS 出力の展示(マルチ表現の比較材料) |
| 8 | **3DTopia-XL** | text / image | PBR GLB | Apache-2.0 / Apache-2.0 | 中程度 | ネイティブ text-to-3D 枠 |
| 9 | **TripoSR** | image | textured mesh | MIT / MIT | ~6GB | 速度・コスト下限の基準線(A100 で 0.5 秒級)。ローカル検証可 |
| 10 | **Stable Fast 3D** (Stability) | image | UV 展開済み textured GLB | Stability Community License(条件付き) | ~6–7GB | UV 展開済みでゲームパイプライン親和。**HF gated、商用登録要件・年商 $1M 条項あり** — サイトで明示 |
| 11 | **Hunyuan3D 2.1** (Tencent) | image | textured mesh(PBR) | Tencent Hunyuan3D 2.1 Community License(**geo 制限付き採用** — 下記参照) | ~29GB(段階ロード必須、A100 fallback 想定) | オープン系最高峰のテクスチャ/PBR 品質。EU/UK/韓国をエッジでブロックして掲載 |

補足:
- 生成時間の公平比較のため、全モデルを段階ゲート方式で RTX 5090 (32GB) に寄せる(`gpu-rental-merged.md` 参照)
- テクスチャなしモデル(TripoSG / Direct3D-S2)はサイト上で「geometry-only」バッジを付け、matcap/wireframe 表示を既定にする
- 費用試算は 8 → 11 モデルに更新が必要(それでも consumer GPU 統一なら素の GPU 代 $10〜15 前後の増加)

## Hunyuan3D 2.1 の扱い: geo 制限付きで採用(2026-07-08 オーナー決定)

**当初はデフォルト除外としたが、オーナーの「サイトは日本内で見られれば OK」という要件を受け、ライセンス準拠の geo 制限を実装して採用する。**

### ライセンス上の根拠(2026-07-08 条文確認)

- LICENSE 5(c) 条: "You must not use, reproduce, modify, distribute, or **display** the Tencent Hunyuan 3D 2.1 Works, **Output** or results ... **outside the Territory**"。Territory = **EU / UK / 韓国を除く全世界**(日本は Territory 内)
- 6(d) 条の「Tencent claims no rights in Outputs」は所有権免責であり、5(c) の契約上の使用制限とは別物(打ち消さない)
- つまり**ブロックすべきは EU 27 カ国 + UK + 韓国のみ**。日本限定にする必要はなく、それ以外の全地域には公開できる
- MAU 条項(月間 100 万超で要追加許諾)は本サイト規模では非該当。AI 生成物である旨の表示は AUP 要件として全モデル共通で実施

### 実装方式(Cloudflare、2026-07-08 仕様確認済み)

- Hunyuan3D 2.1 の成果物(GLB / サムネイル / レンダリング画像)は**専用パスプレフィックス**(例 `/restricted/hunyuan3d-21/`)に隔離する
- **WAF カスタムルール**(Free プランで 5 本まで)1 本でブロック: `http.request.uri.path` が当該プレフィックス かつ `ip.src.country in {…EU27 + GB + KR の29カ国コード列挙…}`(`ip.src.is_in_european_union` フィールドは Business 以上のため Free では列挙で書く)
- WAF はキャッシュ・オリジンフェッチより前段で評価されるため、対象地域からのリクエストが EU 側エッジにアセットを載せる経路を防げる
- アプリ側は Worker で `CF-IPCountry` ヘッダを参照し、対象地域の閲覧者には Hunyuan3D ペインを「ライセンス条項により本地域では表示できません」というプレースホルダ+条項解説に差し替える(**ライセンス差の可視化自体が展示価値になる**)
- **残余リスク(明記)**: 最厳格な読み(EU 内 CDN エッジインフラの存在自体を Territory 外 distribution とみなす読み)を完全に消すには Enterprise の Regional Services が必要。ブロックにより EU PoP へのキャッシュ流入は実質防げるためリスクは低いと判断し、オーナー了承のもと採用する。より保守的に運用する場合は当該パスを **JP のみ許可(allowlist)** に切り替え可能(オーナー要件は満たしたまま)

### 関連事実

- **HY-World 2.0、Hunyuan3D-Part も同一テンプレート条項**(2026-07-08 確認)— Tencent 3D 系を追加する場合は同じ geo 制限パスに載せる
- Hunyuan3D 2.5 / 3.0 / PolyGen は重み非公開のまま(issue #111 未回答)
- サイトには「Hunyuan3D の表示が地域制限される理由」を説明するセクションを設ける(読者が必ず疑問に思う点であり、ライセンス比較自体が本サイトの価値になる)

## 第2弾候補(保留)

- **Hi3DGen**: ジオメトリ精度の評判は高く 2026 年の論文でも現役ベースライン(ShapeGen 論文では TripoSG を僅差で上回る)。ただしオリジナル(bytedance/Hi3DGen、最終 push 2025-09-16)と同系譜 WIP(Stable-X/Stable3DGen、最終 push 2025-07-02)の二重リポ状態で、重みは Stable-X の HF org 側。VRAM 公称値なし(~16GB は未確認の伝聞値)。v1 はジオメトリ枠が TripoSG + Direct3D-S2 で足りるため保留
- **SPAR3D** (Stability): SF3D と同ライセンス。ポイントクラウド編集の展示価値が必要になったら SF3D と交代
- **SAM 3D Objects** (Meta): 遮蔽・自然画像に強い。SAM License は商用可(制裁・軍事等の除外あり)だが**手動 gated** で CI 運用が重い。「散らかったシーンからの復元」専門トラックを作る時に再検討
- **MIDI-3D**(シーン生成、~30GB)/ **AniGen**(リグ付き mesh、依存 CUBVH が非商用)— 専門トラック向け

## 除外(確定)

- **PartPacker / EdgeRunner** (NVIDIA): 非商用ライセンス。パーツ分離は PartCrafter で代替
- **CraftsMan3D**: GitHub は MIT 表記だが**重みは CreativeML OpenRAIL-M**(2026-07-08 確認)— 表記齟齬があり、use-based restrictions を持つ重みでの公開展示はリスク
- **MeshAnything / FastMesh / TreeMeshGPT / MeshRipple**: 一次生成ではなく retopo 系 + ライセンス不明瞭。「生成メッシュのリトポ後比較」を将来やるなら再調査
- **Sparc3D**: 重み・ライセンス未整備のまま(承認待ち表記)
- **InstantMesh / Unique3D / LGM**: 2024 世代で品質的に代替済み
- **Hunyuan3D 2.0**: 2.1 と同ライセンス系で品質は下位互換

## 実行リスク(両調査の統合)

- CUDA 固定の不一致: TRELLIS.2 = CUDA 12.4 / torch 2.6 系、TRELLIS v1 = 11.8/12.2、Direct3D-S2 = torchsparse ソースビルド。5090 (sm_120) 移行は `gpu-rental-merged.md` のゲート方式で吸収
- HF gated(SF3D): トークンと規約承諾を CI に組み込む必要
- TRELLIS.2 はプロジェクトページに academic/research の disclaimer 表記あり(GitHub/HF は MIT)— 取得時点の LICENSE ファイルを成果物と一緒に保存する
- 全モデル共通: 取得した重み・コードのライセンス原文を `runs/` メタデータに同梱し、サイトのモデル詳細ページに表示する
