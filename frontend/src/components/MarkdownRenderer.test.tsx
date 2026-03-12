import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import MarkdownRenderer from './MarkdownRenderer';

/** Wrap with MemoryRouter since claim-field links use react-router <Link>. */
function renderMd(content: string) {
  return render(
    <MemoryRouter>
      <MarkdownRenderer content={content} />
    </MemoryRouter>
  );
}

describe('MarkdownRenderer', () => {
  it('returns null for empty content', () => {
    const { container } = render(<MarkdownRenderer content="" />);
    expect(container.firstChild).toBeNull();
  });

  it('returns null for null content', () => {
    const { container } = render(<MarkdownRenderer content={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders markdown headings', () => {
    renderMd('# Hello World');
    expect(screen.getByText('Hello World')).toBeInTheDocument();
  });

  it('renders markdown paragraphs', () => {
    renderMd('Some paragraph text');
    expect(screen.getByText('Some paragraph text')).toBeInTheDocument();
  });

  it('renders links', () => {
    renderMd('[Click here](https://example.com)');
    const link = screen.getByRole('link', { name: 'Click here' });
    expect(link).toHaveAttribute('href', 'https://example.com');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('renders code blocks', () => {
    renderMd('```\nconst x = 1;\n```');
    expect(screen.getByText(/const x = 1/)).toBeInTheDocument();
  });

  it('renders blockquote', () => {
    renderMd('> A quote');
    expect(screen.getByText('A quote')).toBeInTheDocument();
  });

  it('renders lists', () => {
    renderMd('- Item 1\n- Item 2');
    expect(screen.getByText(/Item 1/)).toBeInTheDocument();
    expect(screen.getByText(/Item 2/)).toBeInTheDocument();
  });

  it('renders mermaid code block with diagram placeholder', async () => {
    renderMd('```mermaid\ngraph TD\nA-->B\n```');
    expect(screen.getByText(/Loading diagram|Rendering diagram/i)).toBeInTheDocument();
  });

  // --- Heading IDs ---

  it('adds id to headings based on text', () => {
    const { container } = renderMd('## Hello World');
    const heading = container.querySelector('h2');
    expect(heading).toHaveAttribute('id', 'hello-world');
  });

  it('de-duplicates repeated heading ids', () => {
    const { container } = renderMd('### Example\n\n### Example\n\n### Example');
    const headings = container.querySelectorAll('h3');
    expect(headings[0]).toHaveAttribute('id', 'example');
    expect(headings[1]).toHaveAttribute('id', 'example-1');
    expect(headings[2]).toHaveAttribute('id', 'example-2');
  });

  // --- Claim-field inline code links ---

  it('renders known claim data field as a link to claim-types docs', () => {
    renderMd('Use the `claim_type` field');
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/docs/claim-types#claim_type');
    // The code element is inside the link
    expect(link.querySelector('code')).toBeInTheDocument();
  });

  it('does not linkify unknown inline code names', () => {
    renderMd('The `someUnknownField` value');
    // No link should be rendered
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText('someUnknownField')).toBeInTheDocument();
  });

  // --- Tree code blocks ---

  it('renders tree code block using <pre><code> with <span> rows', () => {
    const { container } = renderMd('```tree\nsrc/ # root\n└── index.ts\n```');
    const pre = container.querySelector('pre');
    const code = container.querySelector('pre > code');
    expect(pre).toBeInTheDocument();
    expect(code).toBeInTheDocument();
    // Must not contain block-level <div> inside <pre>
    expect(container.querySelector('pre div')).toBeNull();
    // Path parts and comments are rendered
    expect(screen.getByText('src/')).toBeInTheDocument();
    expect(screen.getByText(/root/)).toBeInTheDocument();
  });

  // --- JSON key highlighting ---

  it('highlights JSON keys with amber spans', () => {
    const { container } = renderMd('```json\n{"policy_number": "ABC"}\n```');
    const keySpans = container.querySelectorAll('.text-amber-300');
    expect(keySpans.length).toBeGreaterThan(0);
    expect(keySpans[0].textContent).toContain('policy_number');
  });

  // --- Copy button on fenced code blocks ---

  it('shows a copy button for bash code blocks', () => {
    renderMd('```bash\nclaim-agent run --id 1\n```');
    const btn = screen.getByRole('button', { name: /copy to clipboard/i });
    expect(btn).toBeInTheDocument();
  });

  it('does not show a copy button for plain code blocks', () => {
    renderMd('```\nsome plain code\n```');
    expect(screen.queryByRole('button', { name: /copy/i })).toBeNull();
  });

  // --- CopyButton clipboard handling ---

  describe('CopyButton', () => {
    beforeEach(() => {
      // Provide a mock clipboard
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: vi.fn().mockResolvedValue(undefined) },
        configurable: true,
        writable: true,
      });
    });

    it('shows Copied! after clicking the copy button', async () => {
      renderMd('```bash\nclaim-agent run\n```');
      const btn = screen.getByRole('button', { name: /copy to clipboard/i });
      fireEvent.click(btn);
      await waitFor(() => {
        expect(btn).toHaveAttribute('aria-label', 'Copied!');
      });
    });

    it('does not throw when clipboard is unavailable', async () => {
      Object.defineProperty(navigator, 'clipboard', {
        value: undefined,
        configurable: true,
        writable: true,
      });
      renderMd('```bash\nclaim-agent run\n```');
      const btn = screen.getByRole('button', { name: /copy to clipboard/i });
      // Should not throw
      expect(() => fireEvent.click(btn)).not.toThrow();
    });
  });
});

