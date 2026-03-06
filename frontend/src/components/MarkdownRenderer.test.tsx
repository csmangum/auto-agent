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
});
