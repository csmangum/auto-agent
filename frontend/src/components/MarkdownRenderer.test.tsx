import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import MarkdownRenderer from './MarkdownRenderer';

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
    render(<MarkdownRenderer content="# Hello World" />);
    expect(screen.getByText('Hello World')).toBeInTheDocument();
  });

  it('renders markdown paragraphs', () => {
    render(<MarkdownRenderer content="Some paragraph text" />);
    expect(screen.getByText('Some paragraph text')).toBeInTheDocument();
  });

  it('renders links', () => {
    render(<MarkdownRenderer content="[Click here](https://example.com)" />);
    const link = screen.getByRole('link', { name: 'Click here' });
    expect(link).toHaveAttribute('href', 'https://example.com');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('renders code blocks', () => {
    render(<MarkdownRenderer content={'```\nconst x = 1;\n```'} />);
    expect(screen.getByText(/const x = 1/)).toBeInTheDocument();
  });

  it('renders blockquote', () => {
    render(<MarkdownRenderer content="> A quote" />);
    expect(screen.getByText('A quote')).toBeInTheDocument();
  });

  it('renders lists', () => {
    render(<MarkdownRenderer content="- Item 1\n- Item 2" />);
    expect(screen.getByText(/Item 1/)).toBeInTheDocument();
    expect(screen.getByText(/Item 2/)).toBeInTheDocument();
  });
});
