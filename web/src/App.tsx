import { useState } from 'react';
import { ViewerProvider } from './viewer/ViewerContext';
import { TaskGallery } from './site/TaskGallery';
import { TaskDetail } from './site/TaskDetail';
import { ViewerDemo } from './site/ViewerDemo';

export default function App() {
  const [selectedTask, setSelectedTask] = useState<string | null>(null);

  return (
    <ViewerProvider>
      <div id="app-content" className="max-w-6xl mx-auto px-4 pb-16">
        <header className="pt-8 pb-2">
          <h1 className="text-2xl font-bold">3DGen DemoRoom</h1>
          <p className="text-slate-400 text-sm mt-1">
            オープンソース 3D 生成モデル 11 本を同一課題でベンチマークし、実物のメッシュで比較する
          </p>
        </header>
        {selectedTask ? (
          <TaskDetail taskId={selectedTask} onBack={() => setSelectedTask(null)} />
        ) : (
          <>
            <TaskGallery onSelect={setSelectedTask} />
            <ViewerDemo />
          </>
        )}
      </div>
    </ViewerProvider>
  );
}
