import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  securityLevel: 'strict',
  fontFamily: 'ui-sans-serif, system-ui, sans-serif',
  flowchart: { curve: 'basis', padding: 15 },
  themeVariables: {
    primaryColor: '#dbeafe',
    primaryTextColor: '#1e3a5f',
    primaryBorderColor: '#93c5fd',
    lineColor: '#6b7280',
    secondaryColor: '#f3e8ff',
    tertiaryColor: '#ecfdf5',
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
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-4">
        <p className="text-xs text-amber-600 mb-2 font-medium">Mermaid Diagram (render error)</p>
        <pre className="text-sm text-amber-900 whitespace-pre-wrap font-mono">{chart}</pre>
      </div>
    );
  }

  if (!svg) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 mb-4 text-center">
        <div className="animate-pulse text-gray-400 text-sm">Rendering diagram...</div>
      </div>
    );
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4 overflow-x-auto">
      <div
        ref={containerRef}
        className="flex justify-center [&>svg]:max-w-full"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    </div>
  );
}
