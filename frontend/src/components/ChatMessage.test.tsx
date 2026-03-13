import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import ChatMessage from './ChatMessage';
import type { ChatMessage as ChatMessageType } from '../api/types';

function renderMsg(message: ChatMessageType) {
  return render(
    <MemoryRouter>
      <ChatMessage message={message} />
    </MemoryRouter>
  );
}

describe('ChatMessage', () => {
  it('renders user message', () => {
    renderMsg({ id: '1', role: 'user', content: 'Hello agent' });
    expect(screen.getByText('Hello agent')).toBeInTheDocument();
  });

  it('renders assistant message with markdown', () => {
    renderMsg({ id: '2', role: 'assistant', content: 'The claim is **open**.' });
    expect(screen.getByText(/The claim is/)).toBeInTheDocument();
  });

  it('renders tool call indicator', () => {
    renderMsg({
      id: '3',
      role: 'assistant',
      content: 'Found the claim.',
      toolCalls: [
        { name: 'lookup_claim', args: { claim_id: 'CLM-TEST001' } },
      ],
    });
    expect(screen.getByText(/Looking up claim/)).toBeInTheDocument();
    expect(screen.getByText(/claim_id/)).toBeInTheDocument();
  });

  it('expands tool result on click', () => {
    renderMsg({
      id: '4',
      role: 'assistant',
      content: 'Here are the stats.',
      toolCalls: [
        { name: 'get_claims_stats', args: {}, result: { total_claims: 42 } },
      ],
    });
    const button = screen.getByText(/Getting statistics/);
    fireEvent.click(button);
    expect(screen.getByText(/"total_claims": 42/)).toBeInTheDocument();
  });

  it('renders multiple tool calls', () => {
    renderMsg({
      id: '5',
      role: 'assistant',
      content: 'Done.',
      toolCalls: [
        { name: 'lookup_claim', args: { claim_id: 'CLM-001' } },
        { name: 'get_claim_history', args: { claim_id: 'CLM-001' } },
      ],
    });
    expect(screen.getByText(/Looking up claim/)).toBeInTheDocument();
    expect(screen.getByText(/Getting claim history/)).toBeInTheDocument();
  });

  it('does not render tool calls for user messages', () => {
    renderMsg({
      id: '6',
      role: 'user',
      content: 'Check claim',
      toolCalls: [{ name: 'lookup_claim', args: {} }],
    });
    expect(screen.queryByText(/Looking up claim/)).not.toBeInTheDocument();
  });
});
