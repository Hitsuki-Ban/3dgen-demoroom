const POINTS: { title: string; body: string }[] = [
  {
    title: '同一入力',
    body: '全モデルに同じ正準プロンプト+リファレンス画像+固定シードを与える。25 課題はベースラインから既知の弱点(細い構造、透過素材、セルルック等)までを意図的に突く設計。',
  },
  {
    title: '公式デフォルト・無修正',
    body: '各モデルの公式推奨デフォルト設定のみ使用し、課題別チューニング・手動修正・リテイクは一切なし。失敗もリトライ回数ごと記録する。チェリーピックの余地を仕様で潰している。',
  },
  {
    title: '全データ公開',
    body: '生成時間・ピーク VRAM・使用 GPU・コード/重みのバージョンを課題ごとに記録し、そのまま表示。実行コード・Dockerfile・調査記録はすべて GitHub で公開。',
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
