import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import ChatPanel from './ChatPanel';

// Mock the streamChat function
vi.mock('../api/client', () => ({
  streamChat: vi.fn((_messages, onEvent) => {
    // Simulate a text response
    setTimeout(() => {
      onEvent({ type: 'text', content: 'Hello! I can help with claims.' });
      onEvent({ type: 'done' });
    }, 10);
    return () => {}; // abort function
  }),
}));

function renderPanel() {
  return render(
    <MemoryRouter>
      <ChatPanel />
    </MemoryRouter>
  );
}

describe('ChatPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.runAllTimers();
    vi.useRealTimers();
  });

  it('renders floating button in collapsed state', () => {
    renderPanel();
    const button = screen.getByLabelText('Open chat assistant');
    expect(button).toBeInTheDocument();
  });

  it('opens panel when floating button clicked', () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText('Open chat assistant'));
    // Header title and empty state title both say "Claims Assistant"
    expect(screen.getAllByText('Claims Assistant').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('AI-powered help')).toBeInTheDocument();
  });

  it('shows suggestion prompts when empty', () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText('Open chat assistant'));
    expect(screen.getByText('How many claims are in the system?')).toBeInTheDocument();
    expect(screen.getByText('Show me the review queue')).toBeInTheDocument();
    expect(screen.getByText('What are the escalation thresholds?')).toBeInTheDocument();
  });

  it('fills input when suggestion clicked', () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText('Open chat assistant'));
    const suggestion = screen.getByText('How many claims are in the system?');
    fireEvent.click(suggestion);
    const textarea = screen.getByPlaceholderText('Ask about claims, policies...');
    expect(textarea).toHaveValue('How many claims are in the system?');
  });

  it('closes panel when minimize button clicked', () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText('Open chat assistant'));
    expect(screen.getAllByText('Claims Assistant').length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByLabelText('Close chat'));
    // Panel should be closed, floating button visible again
    expect(screen.getByLabelText('Open chat assistant')).toBeInTheDocument();
  });

  it('has disabled send button when input is empty', () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText('Open chat assistant'));
    const sendBtn = screen.getByLabelText('Send message');
    expect(sendBtn).toBeDisabled();
  });

  it('enables send button when input has text', () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText('Open chat assistant'));
    const textarea = screen.getByPlaceholderText('Ask about claims, policies...');
    fireEvent.change(textarea, { target: { value: 'Hello' } });
    const sendBtn = screen.getByLabelText('Send message');
    expect(sendBtn).not.toBeDisabled();
  });

  it('shows keyboard shortcut hint', () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText('Open chat assistant'));
    expect(screen.getByText(/Shift\+Enter for new line/)).toBeInTheDocument();
  });
});
