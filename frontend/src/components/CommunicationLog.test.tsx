import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import CommunicationLog from './CommunicationLog';

const mockNotes = [
  { id: 1, note: 'Initial contact with claimant', actor_id: 'adjuster-jane', created_at: '2025-01-15T10:00:00Z' },
  { id: 2, note: 'Inspection scheduled', actor_id: 'adjuster-jane', created_at: '2025-01-16T14:00:00Z' },
];

const mockFollowUps = [
  {
    id: 1,
    claim_id: 'CLM-001',
    user_type: 'claimant' as const,
    message_content: 'Please provide photos of the damage',
    status: 'sent',
    created_at: '2025-01-15T11:00:00Z',
  },
  {
    id: 2,
    claim_id: 'CLM-001',
    user_type: 'repair_shop' as const,
    message_content: 'Estimate ready for review',
    status: 'responded',
    response_content: 'Estimate received and reviewed',
    created_at: '2025-01-17T09:00:00Z',
  },
];

const mockAuditEvents = [
  {
    id: 1,
    claim_id: 'CLM-001',
    action: 'status_change',
    old_status: 'pending',
    new_status: 'processing',
    actor_id: 'workflow',
    created_at: '2025-01-15T09:00:00Z',
  },
  {
    id: 2,
    claim_id: 'CLM-001',
    action: 'claim_assigned',
    details: 'Assigned to adjuster-jane',
    actor_id: 'admin',
    created_at: '2025-01-15T09:30:00Z',
  },
];

describe('CommunicationLog', () => {
  it('renders all entries', () => {
    render(
      <CommunicationLog
        notes={mockNotes}
        followUps={mockFollowUps}
        auditEvents={mockAuditEvents}
      />
    );
    expect(screen.getByText('Communication Log')).toBeInTheDocument();
    expect(screen.getByText('Initial contact with claimant')).toBeInTheDocument();
    expect(screen.getByText('Please provide photos of the damage')).toBeInTheDocument();
  });

  it('shows entry count', () => {
    render(
      <CommunicationLog
        notes={mockNotes}
        followUps={mockFollowUps}
        auditEvents={mockAuditEvents}
      />
    );
    expect(screen.getByText('6 entries')).toBeInTheDocument();
  });

  it('filters by notes', () => {
    render(
      <CommunicationLog
        notes={mockNotes}
        followUps={mockFollowUps}
        auditEvents={mockAuditEvents}
      />
    );
    fireEvent.click(screen.getByText('Notes (2)'));
    expect(screen.getByText('Initial contact with claimant')).toBeInTheDocument();
    expect(screen.getByText('Inspection scheduled')).toBeInTheDocument();
    // Follow-ups should not be visible
    expect(screen.queryByText('Please provide photos of the damage')).not.toBeInTheDocument();
  });

  it('filters by follow-ups', () => {
    render(
      <CommunicationLog
        notes={mockNotes}
        followUps={mockFollowUps}
        auditEvents={mockAuditEvents}
      />
    );
    fireEvent.click(screen.getByText('Follow-ups (2)'));
    expect(screen.getByText('Please provide photos of the damage')).toBeInTheDocument();
    expect(screen.queryByText('Initial contact with claimant')).not.toBeInTheDocument();
  });

  it('filters by system events', () => {
    render(
      <CommunicationLog
        notes={mockNotes}
        followUps={mockFollowUps}
        auditEvents={mockAuditEvents}
      />
    );
    fireEvent.click(screen.getByText('System (2)'));
    expect(screen.queryByText('Initial contact with claimant')).not.toBeInTheDocument();
  });

  it('shows empty state when no entries', () => {
    render(
      <CommunicationLog
        notes={[]}
        followUps={[]}
        auditEvents={[]}
      />
    );
    expect(screen.getByText('No communication')).toBeInTheDocument();
  });

  it('sorts entries chronologically (most recent first)', () => {
    render(
      <CommunicationLog
        notes={mockNotes}
        followUps={mockFollowUps}
        auditEvents={mockAuditEvents}
      />
    );
    // Most recent is Jan 17 follow-up "Estimate ready for review"; it should appear before Jan 15/16 entries
    const mostRecentContent = screen.getByText('Estimate ready for review');
    const olderContent = screen.getByText('Initial contact with claimant');
    expect(
      mostRecentContent.compareDocumentPosition(olderContent) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });
});
