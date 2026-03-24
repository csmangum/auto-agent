import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import DocumentVersionCompare from './DocumentVersionCompare';
import type { ClaimDocument } from '../api/types';

function makeDoc(overrides: Partial<ClaimDocument> = {}): ClaimDocument {
  return {
    id: 1,
    claim_id: 'CLM-1',
    document_type: 'estimate',
    review_status: 'pending',
    version: 1,
    storage_key: 'docs/estimate_v1.pdf',
    received_from: null,
    received_date: null,
    created_at: '2025-01-01T00:00:00Z',
    privileged: false,
    extracted_data: null,
    ...overrides,
  } as ClaimDocument;
}

describe('DocumentVersionCompare', () => {
  it('shows info message when fewer than 2 documents', () => {
    render(<DocumentVersionCompare documents={[makeDoc()]} />);
    expect(screen.getByText(/Upload at least two document rows/)).toBeInTheDocument();
  });

  it('shows empty info message with zero documents', () => {
    render(<DocumentVersionCompare documents={[]} />);
    expect(screen.getByText(/Upload at least two document rows/)).toBeInTheDocument();
  });

  it('renders selects when 2+ documents exist', () => {
    const docs = [makeDoc({ id: 1, version: 1 }), makeDoc({ id: 2, version: 2 })];
    render(<DocumentVersionCompare documents={docs} />);
    expect(screen.getByText('Version A')).toBeInTheDocument();
    expect(screen.getByText('Version B')).toBeInTheDocument();
    expect(screen.getAllByRole('combobox')).toHaveLength(2);
  });

  it('shows comparison when two different docs are selected', () => {
    const docs = [
      makeDoc({ id: 1, version: 1, extracted_data: { total: 1000 } }),
      makeDoc({ id: 2, version: 2, extracted_data: { total: 1500 } }),
    ];
    render(<DocumentVersionCompare documents={docs} />);

    const selects = screen.getAllByRole('combobox');
    fireEvent.change(selects[0], { target: { value: '1' } });
    fireEvent.change(selects[1], { target: { value: '2' } });

    expect(screen.getByText('A · v1')).toBeInTheDocument();
    expect(screen.getByText('B · v2')).toBeInTheDocument();
  });

  it('warns when same doc selected for both sides', () => {
    const docs = [makeDoc({ id: 1, version: 1 }), makeDoc({ id: 2, version: 2 })];
    render(<DocumentVersionCompare documents={docs} />);

    const selects = screen.getAllByRole('combobox');
    fireEvent.change(selects[0], { target: { value: '1' } });
    fireEvent.change(selects[1], { target: { value: '1' } });

    expect(
      screen.getByText('Choose two different document rows to compare.')
    ).toBeInTheDocument();
  });

  it('shows dash when extracted_data is null', () => {
    const docs = [
      makeDoc({ id: 1, version: 1, extracted_data: null }),
      makeDoc({ id: 2, version: 2, extracted_data: null }),
    ];
    render(<DocumentVersionCompare documents={docs} />);

    const selects = screen.getAllByRole('combobox');
    fireEvent.change(selects[0], { target: { value: '1' } });
    fireEvent.change(selects[1], { target: { value: '2' } });

    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThanOrEqual(2);
  });
});
