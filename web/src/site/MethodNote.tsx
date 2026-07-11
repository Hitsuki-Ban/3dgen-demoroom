const POINTS: { title: string; body: string }[] = [
  {
    title: '同一入力',
    body: '全モデルに同一のリファレンス画像・プロンプト・固定シードを与える。',
  },
  {
    title: '公式デフォルト・無修正',
    body: '公式デフォルト設定のみ。チューニング・手修正なし、失敗もそのまま公開。',
  },
  {
    title: '全データ公開',
    body: '生成時間・VRAM・GPU・コード/重みのバージョンを課題ごとに記録・表示。',
  },
];

export function MethodNote() {
  return (
    <section className="pt-10">
      <h2 className="text-lg font-semibold pb-3">計測の方針</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {POINTS.map((p) => (
          <div key={p.title} className="rounded-lg border border-slate-700 bg-slate-900/40 px-4 py-3">
            <div className="text-sm font-medium text-sky-300">{p.title}</div>
            <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">{p.body}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-500 mt-3">
        補足: TripoSR / Pixal3D は出力の向きが課題(入力カメラ)ごとに変わるため、既定視点が傾くことがあります — これもモデル特性としてそのまま表示しています。
        詳細なプロトコルは{' '}
        <a
          className="text-sky-400 hover:underline"
          href="https://github.com/Hitsuki-Ban/3dgen-demoroom/blob/main/docs/design/benchmark-tasks.md"
          target="_blank"
          rel="noreferrer"
        >
          docs/design/benchmark-tasks.md
        </a>
        (実行プロトコル §4)を参照。
      </p>
    </section>
  );
}
