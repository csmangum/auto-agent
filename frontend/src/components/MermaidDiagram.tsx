import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  securityLevel: 'strict',
  fontFamily: 'ui-sans-serif, system-ui, sans-serif',
  flowchart: { curve: 'basis', padding: 15 },
  themeVariables: {
    primaryColor: '#1e3a5f',
    primaryTextColor: '#e5e7eb',
    primaryBorderColor: '#4b5563',
    lineColor: '#6b7280',
    secondaryColor: '#312e81',
    tertiaryColor: '#1f2937',
    background: '#111827',
    mainBkg: '#1f2937',
    nodeBorder: '#4b5563',
    clusterBkg: '#1f2937',
    clusterBorder: '#374151',
    titleColor: '#e5e7eb',
    edgeLabelBackground: '#1f2937',
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
      <div className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-8 mb-4 text-center">
        <div className="animate-pulse text-gray-500 text-sm">Rendering diagram…</div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-700/50 rounded-lg p-4 mb-4 overflow-x-auto">
      <div
        ref={containerRef}
        className="flex justify-center [&>svg]:max-w-full"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    </div>
  );
}
