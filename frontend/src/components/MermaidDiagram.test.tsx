import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import MermaidDiagram from './MermaidDiagram';

vi.mock('mermaid', () => ({
  default: {
    render: vi.fn(),
    initialize: vi.fn(),
  },
}));

vi.mock('dompurify', () => ({
  default: {
    sanitize: (html: string) => html,
  },
}));

const mermaid = await import('mermaid');

describe('MermaidDiagram', () => {
  beforeEach(() => {
    vi.mocked(mermaid.default.render).mockReset();
  });

  it('shows loading state when chart is provided and rendering', async () => {
    vi.mocked(mermaid.default.render).mockImplementation(
      () => new Promise(() => {}) // never resolves
    );

    render(<MermaidDiagram chart="graph TD\nA-->B" />);

    expect(screen.getByText('Rendering diagram…')).toBeInTheDocument();
  });

  it('renders SVG when mermaid succeeds', async () => {
    const mockSvg = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>';
    vi.mocked(mermaid.default.render).mockResolvedValue({ svg: mockSvg } as never);

    render(<MermaidDiagram chart="graph TD\nA-->B" />);

    await waitFor(() => {
      expect(document.querySelector('svg')).toBeInTheDocument();
    });
  });

  it('shows error state when mermaid fails', async () => {
    vi.mocked(mermaid.default.render).mockRejectedValue(new Error('Invalid syntax'));

    render(<MermaidDiagram chart="invalid mermaid" />);

    await screen.findByText('Mermaid Diagram (render error)');
    expect(screen.getByText('invalid mermaid')).toBeInTheDocument();
  });

  it('shows error UI when rejection is not Error instance', async () => {
    vi.mocked(mermaid.default.render).mockRejectedValue('string error');

    render(<MermaidDiagram chart="bad chart" />);

    await screen.findByText('Mermaid Diagram (render error)');
    expect(screen.getByText('bad chart')).toBeInTheDocument();
  });

  it('shows loading state for empty chart (mermaid not called)', () => {
    render(<MermaidDiagram chart="" />);

    expect(screen.getByText('Rendering diagram…')).toBeInTheDocument();
    expect(mermaid.default.render).not.toHaveBeenCalled();
  });

  it('trims chart before passing to mermaid', async () => {
    const mockSvg = '<svg></svg>';
    vi.mocked(mermaid.default.render).mockResolvedValue({ svg: mockSvg } as never);

    render(<MermaidDiagram chart={'  graph TD\nA-->B  '} />);

    await waitFor(() => {
      expect(document.querySelector('svg')).toBeInTheDocument();
    });
    const calls = vi.mocked(mermaid.default.render).mock.calls;
    expect(calls[0][0]).toMatch(/^mermaid-\d+$/);
    const chartArg = calls[0][1] as string;
    expect(chartArg.startsWith(' ')).toBe(false);
    expect(chartArg.endsWith(' ')).toBe(false);
    expect(chartArg).toContain('graph TD');
    expect(chartArg).toContain('A-->B');
  });
});
