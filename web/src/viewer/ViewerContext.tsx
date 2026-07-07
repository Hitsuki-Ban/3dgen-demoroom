import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { ViewerCore } from './ViewerCore';

const ViewerContext = createContext<ViewerCore | null>(null);

/** 共有 canvas を 1 枚だけ張り、ViewerCore を配下の ViewerPane に提供する */
export function ViewerProvider({ children }: { children: ReactNode }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [core, setCore] = useState<ViewerCore | null>(null);

  useEffect(() => {
    const c = new ViewerCore(canvasRef.current!);
    setCore(c);
    if (import.meta.env.DEV) (window as unknown as Record<string, unknown>).__viewerCore = c;
    return () => c.dispose();
  }, []);

  return (
    <>
      <canvas id="viewer-canvas" ref={canvasRef} />
      <ViewerContext.Provider value={core}>{children}</ViewerContext.Provider>
    </>
  );
}

export function useViewer(): ViewerCore | null {
  return useContext(ViewerContext);
}
