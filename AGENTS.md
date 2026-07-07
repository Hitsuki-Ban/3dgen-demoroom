# AGENTS.md

このリポジトリは 2 つの AI エージェントと人間オーナーで運営される。

## 役割分担

- **Fable (Claude):** 全体設計、Issue 起票、フロントエンド(Three.js ビューア / UI)実装、PR レビュー・マージ
- **Codex:** リサーチ、ベンチ実行系・モデルラッパー・データ処理などのバックエンド実装、リファレンス画像生成、Fable 発 PR のレビュー・マージ
- **オーナー (Hitsuki-Ban):** レンタル GPU / Cloudflare 等のアカウント・課金提供、最終意思決定

## ワークフロー

1. Fable が Issue を起票する。ラベル `codex` が付いた Issue が Codex への依頼
2. Codex は git worktree で作業し、**ドラフト PR** で提出する(`Closes #N` で Issue に紐付け)
3. Fable がレビューしてマージ。修正依頼は PR 上のコメントで行う
4. Fable 発の PR は Codex がレビュー・マージする

## リポジトリ規約

- デフォルトブランチは `main`。初期スキャフォールドを除き直接 push しない
- Node は **pnpm**、Python は **uv** で管理する(npm / yarn / pip / poetry / conda の直接使用は禁止)
- リサーチ成果物は `docs/research/` に markdown で置く(命名規則はそこの README を参照)

## 情報鮮度ポリシー(重要)

このプロジェクトが扱う 3D 生成分野は数ヶ月単位で状況が変わる。**学習済み知識をそのまま書かないこと。**

- リサーチは必ず Web 検索で執筆時点の状態を検証する
- 出典 URL と確認日付を明記する
- モデル・ライブラリはバージョン番号と最終更新日まで確認する
