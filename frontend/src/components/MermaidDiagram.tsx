import { useEffect, useRef, useState } from 'react';
import DOMPurify from 'dompurify';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  securityLevel: 'strict',
  fontFamily: 'ui-sans-serif, system-ui, sans-serif',
  flowchart: { curve: 'basis', padding: 15, htmlLabels: false },
  themeVariables: {
    primaryColor: '#1e293b',
    primaryTextColor: '#cbd5e1',
    primaryBorderColor: '#64748b',
    lineColor: '#94a3b8',
    secondaryColor: '#334155',
    tertiaryColor: '#475569',
    background: '#0f172a',
    mainBkg: '#1e293b',
    nodeBorder: '#64748b',
    clusterBkg: '#1e293b',
    clusterBorder: '#94a3b8',
    titleColor: '#94a3b8',
    edgeLabelBackground: '#334155',
  },
});

let idCounter = 0;

interface MermaidDiagramProps {
  chart: string;
}

export default function MermaidDiagram({ chart }: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!chart) return;

    const id = `mermaid-${++idCounter}`;
    let cancelled = false;

    mermaid
      .render(id, chart.trim())
      .then(({ svg: renderedSvg }) => {
        if (!cancelled) {
          setSvg(renderedSvg);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to render diagram');
          setSvg('');
        }
      });

    return () => {
      cancelled = true;
    };
  }, [chart]);

  if (error) {
    return (
      <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-4 mb-4">
        <p className="text-xs text-amber-400 mb-2 font-medium">Mermaid Diagram (render error)</p>
        <pre className="text-sm text-amber-300/80 whitespace-pre-wrap font-mono">{chart}</pre>
      </div>
    );
  }

  if (!svg) {
    return (
      <div className="bg-slate-800/50 border border-slate-600/60 rounded-lg p-8 mb-4 text-center">
        <div className="animate-pulse text-slate-400 text-sm">Rendering diagram…</div>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/80 border border-slate-600/60 rounded-lg p-4 mb-4 overflow-x-auto ring-1 ring-slate-600/50">
      <div
        ref={containerRef}
        className="flex justify-center [&>svg]:max-w-full"
        dangerouslySetInnerHTML={{
          __html: DOMPurify.sanitize(svg, {
            USE_PROFILES: { svg: true },
          }),
        }}
      />
    </div>
  );
}
