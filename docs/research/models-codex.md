# OSS 3D生成モデル調査 Codex版

確認日: 2026-07-07 (Asia/Tokyo)

対象: text-to-3D / image-to-3D / mesh生成を中心に、公開展示サイトで横比較するベンチ候補を選ぶ。GitHub / Hugging Face / 公式README / 公式ライセンスを優先して確認した。GitHub の「最終更新」は主に `pushed_at`、Hugging Face は `lastModified` を参照した。

## 結論

デフォルトのベンチラインナップは次の 10 本を推奨する。

1. **TRELLIS.2**: MIT、PBR、複雑トポロジ対応。2026-07時点の品質主力候補。
2. **Pixal3D**: MIT、SIGGRAPH 2026、単画像から textured GLB。新規候補として優先検証。
3. **TripoSG**: MIT、8GB級で回しやすい高品質 shape baseline。
4. **TripoSR**: MIT、古いが高速で安定した低コスト baseline。
5. **Direct3D-S2**: MIT、高解像度 geometry 用。1024 解像度は 24GB 級。
6. **Step1X-3D**: Apache-2.0、geometry + texture の実用候補。
7. **PartCrafter**: MIT、part-aware 出力の差別化枠。
8. **TRELLIS**: MIT、text/image 両方と mesh / 3DGS / radiance field 出力を持つ成熟 baseline。
9. **3DTopia-XL**: Apache-2.0、text/image から PBR GLB。text-to-3D 枠として残す。
10. **Stable Fast 3D**: 速度と GLB 実用性が強い。ただし Stability AI Community License の商用登録・年収閾値を満たす場合のみ。

**Hunyuan3D-2.1 は品質面では強いが、デフォルトの公開展示候補から外す。** Tencent Hunyuan 3D Community License は EU / UK / South Korea を Territory から除外し、Output の表示も Territory 内に限定している。Cloudflare で世界公開するサイトと相性が悪い。採用するなら地域制限、AI生成表示、Tencent非関与の明記、MAU確認を前提にした別トラックにする。

## 推奨ラインナップ

| 優先 | モデル | 入力 | 出力 | ライセンス判断 | 実行目安 | 推奨理由 |
|---:|---|---|---|---|---|---|
| 1 | TRELLIS.2 | image | PBR mesh / GLB相当 | コード MIT、HF重み MIT。依存の nvdiffrast / nvdiffrec 等は別途確認 | NVIDIA 24GB以上、A100/H100検証、CUDA 12.4、H100で 512/1024/1536 の段階生成例あり | 4B image-to-3D。PBR、透過/半透明、任意トポロジ、シャープ特徴が今回の展示価値に合う |
| 2 | Pixal3D | image | textured GLB | コード MIT、HF重み MIT。NOTICEで第三者依存あり | 標準 1536、low-VRAM 1024。低VRAMモードあり | 2026候補。GLB直出し、PBR texture、ComfyUI周辺も出始めている |
| 3 | TripoSG | image / scribble+prompt派生 | GLB mesh | コード MIT、HF重み MIT | CUDA GPU 8GB以上 | TripoSRより新しい高品質 shape baseline。ライセンスが扱いやすい |
| 4 | TripoSR | image | textured mesh / OBJ / GLB | コード・pretrained model MIT | 公式READMEでA100 0.5秒級、単画像デフォルト約6GB VRAM | 速度・安定性・知名度の基準線。最新品質比較の「古典的強基線」として必要 |
| 5 | Direct3D-S2 | image | 高解像度 mesh / OBJ | コード MIT、HF重み MIT | 512で約10GB、1024で約24GB VRAM | 高解像度 geometry の比較枠。textureより形状検分に向く |
| 6 | Step1X-3D | image / control | untextured + textured GLB | コード Apache-2.0、HF重み Apache-2.0 | geometry 1.3B + texture 3.5B。VRAM明記なし、依存重め | permissive license で texture まで含む実用候補 |
| 7 | PartCrafter | image | part / scene mesh | コード MIT、HF重み MIT | 8GB以上。品質優先設定は token 数が重い | part-aware 生成を展示に入れると、単純な一体メッシュ比較との差が出る |
| 8 | TRELLIS | text / image | Radiance Field / 3DGS / mesh | コード MIT、HF重み MIT。FlexiCubes等の依存は別許可 | 16GB以上、Linux、CUDA 11.8/12.2 | text-to-3D と multi-format 出力の成熟 baseline。公式は text→image→image-to-3D を推奨 |
| 9 | 3DTopia-XL | text / image | PBR GLB | コード Apache-2.0、HF重み Apache-2.0 | CUDA 11.8 / PyTorch 2.1 系。VRAM公式値なし | text-to-3D を含む PBR 資産生成枠。やや古いが license が扱いやすい |
| 10 | Stable Fast 3D | image | UV-unwrapped textured GLB | Stability AI Community License。商用利用は登録、年収100万USD超でEnterprise必要 | 約6-7GB、0.5秒級 | 最速級 GLB baseline。公開展示前に組織収益・登録・表示条件を確認 |

SPAR3D は Stable Fast 3D の差し替え候補にする。point cloud edit を比較したいなら有用だが、同じ Stability license であり、まずは SF3D の方が高速 baseline として説明しやすい。

## 全候補比較

| モデル | 開発元 | GitHub / HF 更新 | 入力 | 出力 | コード / 重みライセンス | VRAM・速度・実装 | 採否 |
|---|---|---|---|---|---|---|---|
| TRELLIS.2 | Microsoft | GitHub 2026-06-05 / HF 2025-12-27 | image | PBR mesh assets | MIT / MIT | Linux、24GB以上、CUDA 12.4、flash-attn、nvdiffrast/nvdiffrec/cumesh 等 | **推奨** |
| TRELLIS | Microsoft | GitHub 2026-06-26 / HF image 2024-12-06 / HF text 2025-03-24 | text, image | RF / 3DGS / mesh | MIT / MIT | 16GB以上、CUDA 11.8/12.2。textモデルは品質面で image 経由推奨 | **推奨** |
| Hunyuan3D-2.1 | Tencent | GitHub 2025-10-17 / HF 2025-10-17 | image | shape + PBR texture GLB/OBJ | Tencent Hunyuan 3D Community / 同 | shape 10GB、texture 21GB、合計29GB。custom rasterizer等 | 条件付き。世界公開は非推奨 |
| Hunyuan3D-2 | Tencent | GitHub 2025-10-28 / HF 2025-10-17 | image/text系 | textured mesh | Tencent Hunyuan 3D Community / 同 | shape+texture 16GB級との記述あり。2.1より旧 | 2.1に集約、世界公開は非推奨 |
| Hunyuan3D-Omni | Tencent | GitHub 2025-10-17 | controllable 3D asset | mesh asset | Tencent系 license | 新しいが用途が細分化 | 今回は除外 |
| TripoSR | Tripo AI + Stability AI | GitHub 2026-06-04 / HF 2024-08-09 | image | textured mesh | MIT / MIT | A100 0.5秒級、約6GB VRAM | **推奨** |
| TripoSG | VAST-AI / Tripo | GitHub 2025-04-18 / HF 2025-03-28 | image | GLB mesh | MIT / MIT | 8GB以上、RMBG/DINOv2等 | **推奨** |
| TripoSF | VAST-AI / Tripo | GitHub 2025-04-07 / HF 2025-04-01 | mesh/point cloud系 | 1024^3 SparseFlex mesh | MIT / MIT | 1024^3 は12GB以上 | 端到端生成ではなくコンポーネント候補 |
| MIDI-3D | VAST-AI | GitHub 2025-06-12 / HF 2025-03-09 | single image + segmentation | compositional textured 3D scene | Apache-2.0 / Apache-2.0 | 約30GB VRAM、MV-Adapter依存 | 場面生成の专项候補 |
| AniGen | VAST-AI | GitHub 2026-07-06 / HF 2026-04-13 | image | rigged mesh, skeleton GLB, skin weights | コード MIT、第三者 CUBVH は非商用研究制限 | 18GB以上との報告、spconv/pytorch3d/nvdiffrast | アニメーション专项候補。通常ベンチ外 |
| DetailGen3D | VAST-AI | GitHub 2025-04-18 / HF 2025-04-17 | coarse mesh + image | enhanced geometry | MIT / MIT | 後処理型。VRAM明記なし | 後処理比較候補 |
| Stable Fast 3D | Stability AI | GitHub 2025-01-22 / HF 2025-04-08 | image | UV-unwrapped textured GLB | Stability AI Community / 同、HF gated | 約6GB VRAM、0.5秒級 | **条件付き推奨** |
| SPAR3D | Stability AI | GitHub 2025-05-05 / HF 2025-04-08 | image / point edit | textured GLB | Stability AI Community / 同、HF gated | デフォルト10.5GB、low VRAM約7GB | 条件付き。SF3Dの代替 |
| InstantMesh | TencentARC | GitHub 2025-01-03 / HF 2024-04-11 | image | OBJ, texture map option | Apache-2.0 / Apache-2.0 | CUDA 12.1、xformers、Dockerあり | 古いが permissive baseline |
| Pixal3D | TencentARC | GitHub 2026-06-23 / HF 2026-05-24 | image | textured GLB | MIT / MIT | 1536標準、1024 low-VRAM、FlashAttention等 | **推奨** |
| CraftsMan3D | HKUST-SAIL | GitHub 2025-06-26 / HF 2024-11-25 | text/image | coarse mesh + refined mesh | GitHub本文はMIT、HFは CreativeML OpenRAIL-M | coarse 5秒 + refine 20秒、Dockerあり | license差分があり慎重。通常ベンチ外 |
| Unique3D | AiuniAI | GitHub 2025-07-17 | image | textured mesh | MIT / MIT | 約30秒、入力視角に敏感 | 軽量 baseline 補欠 |
| LGM | 3DTopia / ashawkey | GitHub 2024-08-20 / HF 2025-05-16 | text/image | Gaussian / mesh | MIT / MIT | 約5秒、diff-gaussian-rasterization | 古い高速 baseline 補欠 |
| Step1X-3D | StepFun | GitHub 2025-09-08 / HF 2025-05-13 | image/control | GLB mesh + texture | Apache-2.0 / Apache-2.0 | 大型 geometry + texture pipeline | **推奨** |
| Direct3D-S2 | DreamTechAI | GitHub 2025-09-26 / HF 2025-06-14 | image | OBJ geometry | MIT / MIT | 512 約10GB、1024 約24GB、Dockerあり | **推奨** |
| Hi3DGen | ByteDance | GitHub 2025-09-16 | image/normal bridge | high-detail geometry | MIT / MIT | spconv/xformers/CUDA依存、VRAM明記なし | geometry専用候補。texture弱め |
| Sparc3D | Lizhihao / Math Magic | GitHub 2025-06-16 | image/mesh latent | 1024^3 high-res surface | license/weights未整備 | code approval待ち表記あり | ローカルベンチ除外 |
| PartPacker | NVIDIA | GitHub 2025-06-26 / HF 2025-06-16 | image | part-level object | NVIDIA Source Code License、非商用研究限定 | fp16 約10GB、Dockerあり | 公開製品寄り展示は除外 |
| PartCrafter | wgsxm | GitHub 2026-04-16 / HF 2025-07-12 | image | structured part / scene meshes | MIT / MIT | 8GB以上、TripoSG系VAE | **推奨** |
| 3DTopia-XL | 3DTopia | GitHub 2025-07-14 / HF 2024-09-20 | text/image | PBR GLB | Apache-2.0 / Apache-2.0 | CUDA 11.8/PyTorch 2.1、VRAM明記なし | **推奨** |
| MeshAnything / V2 | PKU / S-Lab | GitHub 2025-04-28 | mesh/point cloud | artist low-poly mesh | S-Lab NC / HF表記に揺れあり | A6000で7-8GB、30-45秒、800-1600 faces | retopo参考。公開商用は除外 |
| EdgeRunner | NVIDIA | GitHub 2024-12-22 | mesh | autoregressive artist mesh | NVIDIA Source Code License、非商用 + NVIDIA processor制限 | 4000 faces級 | 除外 |
| SAM 3D Objects | Meta | GitHub 2026-06-02 / HF 2026-06-12 | image / masked objects | pose, shape, texture, layout, PLY splat | SAM License、HF manual gated | 自然画像・遮蔽に強いが権限取得が必要 | 合規後の专项候補 |
| TreeMeshGPT | SAIL | GitHub 2025-05-22 | point cloud / dense mesh | artist mesh | MIT / Google Drive重みは要確認 | 5500-11000 faces | retopo参考。主ベンチ外 |
| MeshRipple | MayMhappy | GitHub 2026-04-10 | point cloud / TRELLIS由来二段階 | artist mesh | 未明示 / 未明示 | Python 3.12、FlashAttention、KV cache未実装 | 新しいが license/速度リスク |
| FastMesh | jhkim0759 | 3DV 2026 / HF weights | point cloud | artist mesh | S-Lab NC系 | A6000/CUDA 11.8 | 公開商用は除外 |

## ライセンス上の注意

- **Tencent Hunyuan3D / UltraShape 系:** Tencent Hunyuan 3D Community License は EU / UK / South Korea を Territory から除外し、Outputs の display / distribute も Territory 内に限定する。Tencent は Outputs の権利を主張しないが、公開展示サイトで該当地域から見える状態はライセンス外になり得る。100万 MAU 超は追加許諾が必要。
- **Stability AI Community License:** non-commercial / research と限定 commercial は可能。ただし commercial use は登録が必要で、Licensee と affiliates の年間 revenue が 100万 USD を超えると Enterprise License が必要。Output はユーザー所有とされるが、foundation generative AI model の改良用途は禁止。
- **NVIDIA Source Code License:** PartPacker、EdgeRunner、nvdiffrast/nvdiffrec/GET3D周辺は research / non-commercial 条件が混ざる。展示サイトが非営利でも、スポンサー・商用文脈・公開サービス化の可能性を考えると default lineup から外すのが安全。
- **MIT / Apache でも依存は別:** TRELLIS.2、Pixal3D、AniGen などは本体が permissive でも、CUDA extension や第三者コードの NOTICE を bench 実行前に再確認する。
- **TRELLIS.2 の表示ゆれ:** GitHub / HF の license は MIT だが、プロジェクトページには掲載 materials の academic / research 目的 disclaimer がある。実行時は GitHub / HF から取得する artifact の license を保存し、商用文脈では Microsoft 側の最新表示を再確認する。
- **生成物の公開権利:** モデル license とは別に、入力画像・prompt・商標・キャラクター類似性の権利処理が必要。ベンチ課題は自作 reference 画像か権利クリアな素材に限定する。

## 実行リスク

- **CUDA 固定:** TRELLIS.2 は CUDA 12.4 / PyTorch 2.6 系、TRELLIS は CUDA 11.8/12.2、Direct3D-S2 は 1024 で 24GB 級。レンタルGPUのベースイメージと合わないと extension build で時間を失う。
- **flash-attn / xformers / spconv:** Ampere/Ada/Hopper 世代の wheel 組み合わせを先に固定する。V100 や古いCUDAは候補から外す。
- **Docker 公式対応のばらつき:** Hunyuan3D、InstantMesh、PartPacker、Direct3D-S2 は Docker 情報が比較的ある。TRELLIS.2、Pixal3D、TripoSG は Dockerfileを自前で作る前提に近い。
- **Texture と GLB 統一:** geometry-only モデルは Three.js 展示では見劣りする。matcap / wireframe / normal 表示と、別途 texture stage の有無を明示する。
- **HF gated models:** Stability と SAM 3D Objects は利用規約承諾・token・manual approval が CI / rental GPU で詰まりやすい。

## 除外・保留したモデル

- **Hunyuan3D-2.1 / 2.0:** 品質は高いが、世界公開展示との license mismatch が大きい。地域制限を実装するなら別途採用検討。
- **PartPacker / EdgeRunner:** NVIDIA Source Code License の non-commercial / research 制限により、展示サイトの主候補から外す。
- **Sparc3D:** 高解像度表面生成として有望だが、ローカル実行用の license/weights が未整備。
- **MeshAnything / FastMesh / TreeMeshGPT / MeshRipple:** mesh retopology / artist mesh 生成であり、text/image-to-mesh の一次生成モデルではない。後処理比較なら再検討。
- **TripoSF:** 端到端の image-to-3D 主モデルではなく、representation / decoder 寄り。TripoSG を優先。
- **CraftsMan3D:** GitHub本文と HF license 表記の差があり、依存も重い。研究参考に留める。
- **SAM 3D Objects:** 自然画像の実用性は高いが SAM License と manual gated weight の運用負担がある。masked-object / cluttered-scene の专项ベンチを立てる時に再検討。
- **AniGen:** rigged mesh は展示価値が高いが、第三者 CUBVH の非商用研究制限がある。通常の static asset 比較から外し、animation 展示が必要になった時だけ专项化する。

## 参考URL

### 推奨候補

- TRELLIS GitHub: https://github.com/microsoft/TRELLIS
- TRELLIS project page: https://microsoft.github.io/TRELLIS/
- TRELLIS image weights: https://huggingface.co/microsoft/TRELLIS-image-large
- TRELLIS text weights: https://huggingface.co/microsoft/TRELLIS-text-large
- TRELLIS.2 GitHub: https://github.com/microsoft/TRELLIS.2
- TRELLIS.2 project page: https://microsoft.github.io/TRELLIS.2/
- TRELLIS.2 weights: https://huggingface.co/microsoft/TRELLIS.2-4B
- Pixal3D GitHub: https://github.com/TencentARC/Pixal3D
- Pixal3D weights: https://huggingface.co/TencentARC/Pixal3D
- TripoSR GitHub: https://github.com/VAST-AI-Research/TripoSR
- TripoSR weights: https://huggingface.co/stabilityai/TripoSR
- TripoSG GitHub: https://github.com/VAST-AI-Research/TripoSG
- TripoSG weights: https://huggingface.co/VAST-AI/TripoSG
- Direct3D-S2 GitHub: https://github.com/DreamTechAI/Direct3D-S2
- Direct3D-S2 weights: https://huggingface.co/wushuang98/Direct3D-S2
- Step1X-3D GitHub: https://github.com/stepfun-ai/Step1X-3D
- Step1X-3D weights: https://huggingface.co/stepfun-ai/Step1X-3D
- PartCrafter GitHub: https://github.com/wgsxm/PartCrafter
- PartCrafter weights: https://huggingface.co/wgsxm/PartCrafter
- 3DTopia-XL GitHub: https://github.com/3DTopia/3DTopia-XL
- 3DTopia-XL weights: https://huggingface.co/3DTopia/3DTopia-XL
- Stable Fast 3D GitHub: https://github.com/Stability-AI/stable-fast-3d
- Stable Fast 3D weights: https://huggingface.co/stabilityai/stable-fast-3d

### 条件付き・除外候補

- Hunyuan3D-2 GitHub: https://github.com/Tencent-Hunyuan/Hunyuan3D-2
- Hunyuan3D-2 weights: https://huggingface.co/tencent/Hunyuan3D-2
- Hunyuan3D-2.1 GitHub: https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1
- Hunyuan3D-2.1 weights: https://huggingface.co/tencent/Hunyuan3D-2.1
- Tencent Hunyuan3D-2.1 License: https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE
- SPAR3D GitHub: https://github.com/Stability-AI/stable-point-aware-3d
- SPAR3D weights: https://huggingface.co/stabilityai/stable-point-aware-3d
- Stability AI Community License FAQ: https://stability.ai/license
- InstantMesh GitHub: https://github.com/TencentARC/InstantMesh
- InstantMesh weights: https://huggingface.co/TencentARC/InstantMesh
- TripoSF GitHub: https://github.com/VAST-AI-Research/TripoSF
- TripoSF weights: https://huggingface.co/VAST-AI/TripoSF
- MIDI-3D GitHub: https://github.com/VAST-AI-Research/MIDI-3D
- MIDI-3D weights: https://huggingface.co/VAST-AI/MIDI-3D
- AniGen GitHub: https://github.com/VAST-AI-Research/AniGen
- DetailGen3D GitHub: https://github.com/VAST-AI-Research/DetailGen3D
- CraftsMan3D GitHub: https://github.com/HKUST-SAIL/CraftsMan3D
- CraftsMan weights: https://huggingface.co/craftsman3d/craftsman
- Unique3D GitHub: https://github.com/AiuniAI/Unique3D
- LGM GitHub: https://github.com/3DTopia/LGM
- Hi3DGen GitHub: https://github.com/bytedance/Hi3DGen
- Sparc3D GitHub: https://github.com/lizhihao6/Sparc3D
- PartPacker GitHub: https://github.com/NVlabs/PartPacker
- PartPacker weights: https://huggingface.co/nvidia/PartPacker
- NVIDIA PartPacker license: https://github.com/NVlabs/PartPacker/blob/main/license.md
- MeshAnything GitHub: https://github.com/buaacyw/MeshAnything
- MeshAnythingV2 GitHub: https://github.com/buaacyw/MeshAnythingV2
- EdgeRunner GitHub: https://github.com/NVlabs/EdgeRunner
- SAM 3D Objects GitHub: https://github.com/facebookresearch/sam-3d-objects
- SAM 3D Objects weights: https://huggingface.co/facebook/sam-3d-objects
- TreeMeshGPT GitHub: https://github.com/sail-sg/TreeMeshGPT
- MeshRipple GitHub: https://github.com/MayMhappy/MeshRipple
- FastMesh GitHub: https://github.com/jhkim0759/FastMesh
