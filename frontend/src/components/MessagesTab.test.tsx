import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MessagesTab from './MessagesTab';
import * as client from '../api/client';

vi.mock('../api/client', () => ({
  postClaimFollowUpResponse: vi.fn(),
}));

const mockPostClaimFollowUpResponse = vi.mocked(client.postClaimFollowUpResponse);

function renderMessagesTab(props: {
  followUps?: Array<{
    id: number;
    claim_id: string;
    user_type: string;
    message_content: string;
    status: string;
    response_content?: string;
    created_at?: string;
  }>;
  claimId?: string;
  accentColor?: 'emerald' | 'amber' | 'purple';
  senderLabel?: string;
  emptyTitle?: string;
  emptyDescription?: string;
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const defaultProps = {
    followUps: props.followUps ?? [],
    claimId: props.claimId ?? 'CLM-TEST001',
    accentColor: (props.accentColor ?? 'emerald') as 'emerald' | 'amber' | 'purple',
    senderLabel: props.senderLabel ?? 'From: Claims Team',
    emptyTitle: props.emptyTitle,
    emptyDescription: props.emptyDescription,
  };
  return render(
    <QueryClientProvider client={queryClient}>
      <MessagesTab {...defaultProps} />
    </QueryClientProvider>
  );
}

describe('MessagesTab', () => {
  beforeEach(() => {
    mockPostClaimFollowUpResponse.mockReset();
  });

  it('shows empty state when no messages', () => {
    renderMessagesTab({ followUps: [] });
    expect(screen.getByText('No messages')).toBeInTheDocument();
    expect(screen.getByText('No messages yet.')).toBeInTheDocument();
  });

  it('shows custom empty title and description', () => {
    renderMessagesTab({
      followUps: [],
      emptyTitle: 'No communications',
      emptyDescription: 'No inter-carrier communications yet.',
    });
    expect(screen.getByText('No communications')).toBeInTheDocument();
    expect(screen.getByText('No inter-carrier communications yet.')).toBeInTheDocument();
  });

  it('renders message list', () => {
    renderMessagesTab({
      followUps: [
        {
          id: 1,
          claim_id: 'CLM-TEST001',
          user_type: 'claimant',
          message_content: 'Please provide your repair estimate.',
          status: 'sent',
          created_at: '2025-01-15T10:00:00Z',
        },
      ],
    });
    expect(screen.getByText('Please provide your repair estimate.')).toBeInTheDocument();
    expect(screen.getByText(/From: Claims Team/)).toBeInTheDocument();
  });

  it('shows Reply button for sent messages', () => {
    renderMessagesTab({
      followUps: [
        {
          id: 1,
          claim_id: 'CLM-TEST001',
          user_type: 'claimant',
          message_content: 'Please respond.',
          status: 'sent',
        },
      ],
    });
    expect(screen.getByRole('button', { name: /Reply to this message|Reply/ })).toBeInTheDocument();
  });

  it('shows response form when Reply clicked', () => {
    renderMessagesTab({
      followUps: [
        {
          id: 1,
          claim_id: 'CLM-TEST001',
          user_type: 'claimant',
          message_content: 'Please respond.',
          status: 'sent',
        },
      ],
    });
    fireEvent.click(screen.getByRole('button', { name: /Reply/ }));
    expect(screen.getByPlaceholderText('Type your response...')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send Response' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  it('submits response and shows success', async () => {
    mockPostClaimFollowUpResponse.mockResolvedValue({ success: true, message: 'Response recorded' });
    renderMessagesTab({
      followUps: [
        {
          id: 1,
          claim_id: 'CLM-TEST001',
          user_type: 'claimant',
          message_content: 'Please respond.',
          status: 'sent',
        },
      ],
    });
    fireEvent.click(screen.getByRole('button', { name: /Reply/ }));
    fireEvent.change(screen.getByPlaceholderText('Type your response...'), {
      target: { value: 'Here is my response.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send Response' }));

    await waitFor(() => {
      expect(mockPostClaimFollowUpResponse).toHaveBeenCalledWith('CLM-TEST001', {
        message_id: 1,
        response_content: 'Here is my response.',
      });
    });
    expect(screen.getByText('Response submitted')).toBeInTheDocument();
  });

  it('shows error when submit fails', async () => {
    mockPostClaimFollowUpResponse.mockRejectedValue(new Error('Network error'));
    renderMessagesTab({
      followUps: [
        {
          id: 1,
          claim_id: 'CLM-TEST001',
          user_type: 'claimant',
          message_content: 'Please respond.',
          status: 'sent',
        },
      ],
    });
    fireEvent.click(screen.getByRole('button', { name: /Reply/ }));
    fireEvent.change(screen.getByPlaceholderText('Type your response...'), {
      target: { value: 'My response' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send Response' }));

    await waitFor(() => {
      expect(screen.getByText(/Error: Network error/)).toBeInTheDocument();
    });
  });

  it('does not submit when response is empty', async () => {
    renderMessagesTab({
      followUps: [
        {
          id: 1,
          claim_id: 'CLM-TEST001',
          user_type: 'claimant',
          message_content: 'Please respond.',
          status: 'sent',
        },
      ],
    });
    fireEvent.click(screen.getByRole('button', { name: /Reply/ }));
    const sendBtn = screen.getByRole('button', { name: 'Send Response' });
    expect(sendBtn).toBeDisabled();
  });

  it('Cancel closes response form', () => {
    renderMessagesTab({
      followUps: [
        {
          id: 1,
          claim_id: 'CLM-TEST001',
          user_type: 'claimant',
          message_content: 'Please respond.',
          status: 'sent',
        },
      ],
    });
    fireEvent.click(screen.getByRole('button', { name: /Reply/ }));
    expect(screen.getByPlaceholderText('Type your response...')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByPlaceholderText('Type your response...')).not.toBeInTheDocument();
  });
});
