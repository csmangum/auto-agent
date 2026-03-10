import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import AuditTimeline from './AuditTimeline';
import type { AuditEvent } from '../api/types';

describe('AuditTimeline', () => {
  it('shows empty state when no events', () => {
    render(<AuditTimeline events={[]} />);
    expect(screen.getByText('No audit events')).toBeInTheDocument();
  });

  it('renders audit events', () => {
    const events: AuditEvent[] = [
      {
        claim_id: 'CLM-001',
        action: 'claim_created',
        created_at: '2025-01-15 10:00:00',
      },
    ];
    render(<AuditTimeline events={events} />);
    expect(screen.getByText('claim created')).toBeInTheDocument();
  });

  it('renders status change with state diff toggle', () => {
    const events: AuditEvent[] = [
      {
        claim_id: 'CLM-001',
        action: 'status_change',
        old_status: 'pending',
        new_status: 'open',
        before_state: '{"a":1}',
        after_state: '{"a":2}',
        created_at: '2025-01-15 10:00:00',
      },
    ];
    render(<AuditTimeline events={events} />);
    expect(screen.getByText('status change')).toBeInTheDocument();
    expect(screen.getByText('open')).toBeInTheDocument();
    const toggleBtn = screen.getByRole('button', { name: /show state diff/i });
    fireEvent.click(toggleBtn);
    expect(screen.getByText('Hide state diff')).toBeInTheDocument();
  });
});
