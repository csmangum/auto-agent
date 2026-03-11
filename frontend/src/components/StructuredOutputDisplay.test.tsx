import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import StructuredOutputDisplay from './StructuredOutputDisplay';

describe('StructuredOutputDisplay', () => {
  it('shows em dash for empty or whitespace value', () => {
    render(<StructuredOutputDisplay value="" />);
    expect(screen.getByText('—')).toBeInTheDocument();

    render(<StructuredOutputDisplay value="   " />);
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1);
  });

  it('falls back to raw text for non-JSON', () => {
    render(<StructuredOutputDisplay value="plain text output" />);
    expect(screen.getByText('plain text output')).toBeInTheDocument();
  });

  it('falls back to raw text for malformed JSON', () => {
    render(<StructuredOutputDisplay value='{"invalid": json' />);
    expect(screen.getByText(/invalid/)).toBeInTheDocument();
  });

  it('truncates long raw text with ellipsis', () => {
    const long = 'x'.repeat(600);
    render(<StructuredOutputDisplay value={long} />);
    expect(screen.getByText(/…/)).toBeInTheDocument();
  });

  it('parses escalation JSON and renders priority, reasons, indicators', () => {
    const json = JSON.stringify({
      escalation_reasons: ['fraud_suspected'],
      priority: 'critical',
      recommended_action: 'Review manually.',
      fraud_indicators: ['multiple_claims_same_vin'],
    });
    render(<StructuredOutputDisplay value={json} />);
    expect(screen.getByText('Priority')).toBeInTheDocument();
    expect(screen.getByText('critical')).toBeInTheDocument();
    expect(screen.getByText('Reasons')).toBeInTheDocument();
    expect(screen.getByText('fraud suspected')).toBeInTheDocument();
    expect(screen.getByText(/Review manually/)).toBeInTheDocument();
    expect(screen.getByText('multiple claims same vin')).toBeInTheDocument();
  });

  it('uses medium badge for unknown priority', () => {
    const json = JSON.stringify({
      escalation_reasons: ['other'],
      priority: 'unknown_priority',
    });
    render(<StructuredOutputDisplay value={json} />);
    expect(screen.getByText('unknown_priority')).toBeInTheDocument();
  });

  it('handles empty escalation_reasons and fraud_indicators', () => {
    const json = JSON.stringify({
      priority: 'high',
      reason: 'Low confidence',
    });
    render(<StructuredOutputDisplay value={json} />);
    expect(screen.getByText('Priority')).toBeInTheDocument();
    expect(screen.getByText('high')).toBeInTheDocument();
    expect(screen.getByText('Reason')).toBeInTheDocument();
    expect(screen.getByText('Low confidence')).toBeInTheDocument();
  });

  it('parses state snapshot JSON with status, claim_type, payout', () => {
    const json = JSON.stringify({
      status: 'processing',
      claim_type: 'partial_loss',
      payout_amount: 5000,
    });
    render(<StructuredOutputDisplay value={json} />);
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('processing')).toBeInTheDocument();
    expect(screen.getByText('Claim type')).toBeInTheDocument();
    expect(screen.getByText('partial_loss')).toBeInTheDocument();
    expect(screen.getByText('Payout')).toBeInTheDocument();
    expect(screen.getByText('$5,000')).toBeInTheDocument();
  });

  it('parses router JSON with claim_type, confidence, reasoning', () => {
    const json = JSON.stringify({
      claim_type: 'total_loss',
      confidence: 0.92,
      reasoning: 'Vehicle damage exceeds threshold.',
    });
    render(<StructuredOutputDisplay value={json} />);
    expect(screen.getByText('Claim type')).toBeInTheDocument();
    expect(screen.getByText('total loss')).toBeInTheDocument();
    expect(screen.getByText('Confidence')).toBeInTheDocument();
    expect(screen.getByText('92%')).toBeInTheDocument();
    expect(screen.getByText('Reasoning')).toBeInTheDocument();
    expect(screen.getByText('Vehicle damage exceeds threshold.')).toBeInTheDocument();
  });

  it('prefers escalation over state snapshot when both match', () => {
    const json = JSON.stringify({
      status: 'processing',
      claim_type: 'partial_loss',
      escalation_reasons: ['fraud_suspected'],
      priority: 'high',
    });
    render(<StructuredOutputDisplay value={json} />);
    expect(screen.getByText('Priority')).toBeInTheDocument();
    expect(screen.getByText('high')).toBeInTheDocument();
    expect(screen.getByText('Reasons')).toBeInTheDocument();
    expect(screen.getByText('fraud suspected')).toBeInTheDocument();
  });

  it('prefers state snapshot over router when both match', () => {
    const json = JSON.stringify({
      status: 'open',
      claim_type: 'partial_loss',
      payout_amount: null,
      confidence: 0.9,
      reasoning: 'Some reasoning',
    });
    render(<StructuredOutputDisplay value={json} />);
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('open')).toBeInTheDocument();
    expect(screen.getByText('Claim type')).toBeInTheDocument();
    expect(screen.getByText('Payout')).toBeInTheDocument();
  });
});
