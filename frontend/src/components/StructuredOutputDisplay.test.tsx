import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import StructuredOutputDisplay from './StructuredOutputDisplay';

describe('StructuredOutputDisplay', () => {
  it('renders empty state for empty or whitespace string', () => {
    render(<StructuredOutputDisplay value="" />);
    expect(screen.getByText('—')).toBeInTheDocument();

    render(<StructuredOutputDisplay value="   " />);
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1);
  });

  it('renders empty state for undefined value', () => {
    render(<StructuredOutputDisplay value={undefined} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('falls back to raw display for plain text', () => {
    const text = 'Claim processed successfully. Settlement completed.';
    render(<StructuredOutputDisplay value={text} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it('renders malformed JSON as raw text', () => {
    const payload = '{"invalid": json';
    render(<StructuredOutputDisplay value={payload} />);
    expect(screen.getByText(payload)).toBeInTheDocument();
  });

  it('truncates fallback when maxLength is set', () => {
    const text = 'a'.repeat(600);
    render(<StructuredOutputDisplay value={text} maxLength={100} />);
    expect(screen.getByText('a'.repeat(100) + '…')).toBeInTheDocument();
  });

  it('does not truncate fallback when maxLength is omitted', () => {
    const text = 'x'.repeat(600);
    render(<StructuredOutputDisplay value={text} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it('parses and renders escalation payload with all fields', () => {
    const payload = JSON.stringify({
      escalation_reasons: ['fraud_suspected', 'low_confidence'],
      priority: 'critical',
      recommended_action: 'Review claim manually.',
      fraud_indicators: ['value_mismatch'],
      reason: 'Multiple indicators',
      router_confidence: 0.4,
      router_confidence_threshold: 0.7,
    });
    render(<StructuredOutputDisplay value={payload} />);
    expect(screen.getByText('Priority')).toBeInTheDocument();
    expect(screen.getByText('critical')).toBeInTheDocument();
    expect(screen.getByText('Reasons')).toBeInTheDocument();
    expect(screen.getByText('fraud suspected')).toBeInTheDocument();
    expect(screen.getByText('low confidence')).toBeInTheDocument();
    expect(screen.getByText(/Review claim manually/)).toBeInTheDocument();
    expect(screen.getByText('value mismatch')).toBeInTheDocument();
    expect(screen.getByText('Reason')).toBeInTheDocument();
    expect(screen.getByText('Multiple indicators')).toBeInTheDocument();
    expect(screen.getByText(/Confidence 0.4 below threshold 0.7/)).toBeInTheDocument();
  });

  it('parses and renders state snapshot with status, claim_type, payout_amount', () => {
    const payload = JSON.stringify({
      status: 'settled',
      claim_type: 'partial_loss',
      payout_amount: 2500,
    });
    render(<StructuredOutputDisplay value={payload} />);
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('settled')).toBeInTheDocument();
    expect(screen.getByText('Claim type')).toBeInTheDocument();
    expect(screen.getByText('partial loss')).toBeInTheDocument();
    expect(screen.getByText('Payout')).toBeInTheDocument();
    expect(screen.getByText('$2,500')).toBeInTheDocument();
  });

  it('parses and renders router payload with claim_type, confidence, reasoning', () => {
    const payload = JSON.stringify({
      claim_type: 'total_loss',
      confidence: 0.92,
      reasoning: 'Vehicle damage exceeds 75% of ACV.',
    });
    render(<StructuredOutputDisplay value={payload} />);
    expect(screen.getByText('Claim type')).toBeInTheDocument();
    expect(screen.getByText('total loss')).toBeInTheDocument();
    expect(screen.getByText('Confidence')).toBeInTheDocument();
    expect(screen.getByText('92%')).toBeInTheDocument();
    expect(screen.getByText('Reasoning')).toBeInTheDocument();
    expect(screen.getByText(/Vehicle damage exceeds/)).toBeInTheDocument();
  });

  it('handles confidence as 0-100 when value exceeds 1', () => {
    const payload = JSON.stringify({
      claim_type: 'partial_loss',
      confidence: 85,
      reasoning: 'Minor damage.',
    });
    render(<StructuredOutputDisplay value={payload} />);
    expect(screen.getByText('85%')).toBeInTheDocument();
  });

  it('falls back to raw display for unrecognized JSON', () => {
    const payload = '{"foo": "bar", "baz": 123}';
    render(<StructuredOutputDisplay value={payload} />);
    expect(screen.getByText(payload)).toBeInTheDocument();
  });

  it('uses escalation parse when JSON matches both escalation and state snapshot', () => {
    const payload = JSON.stringify({
      escalation_reasons: ['fraud_suspected'],
      status: 'needs_review',
      claim_type: 'partial_loss',
      payout_amount: null,
    });
    render(<StructuredOutputDisplay value={payload} />);
    expect(screen.getByText('Reasons')).toBeInTheDocument();
    expect(screen.getByText('fraud suspected')).toBeInTheDocument();
    expect(screen.queryByText('Claim type')).not.toBeInTheDocument();
  });

  it('handles escalation_reasons as single string (coerces to array)', () => {
    const payload = JSON.stringify({
      escalation_reasons: 'fraud_suspected',
      priority: 'high',
    });
    render(<StructuredOutputDisplay value={payload} />);
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

  it('renders audit variant for state snapshot', () => {
    const payload = JSON.stringify({
      status: 'processing',
      claim_type: null,
      payout_amount: null,
    });
    render(<StructuredOutputDisplay value={payload} variant="audit" />);
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('Claim type')).toBeInTheDocument();
    expect(screen.getByText('Payout')).toBeInTheDocument();
    expect(screen.getByText('processing')).toBeInTheDocument();
  });
});
