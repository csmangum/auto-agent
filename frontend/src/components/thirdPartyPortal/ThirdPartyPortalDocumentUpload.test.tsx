import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ThirdPartyPortalDocumentUpload } from './ThirdPartyPortalDocumentUpload';

describe('ThirdPartyPortalDocumentUpload', () => {
  const defaultProps = {
    claimId: 'CLM-1',
    onUploaded: vi.fn(),
    uploadFn: vi.fn(),
  };

  it('renders upload form', () => {
    render(<ThirdPartyPortalDocumentUpload {...defaultProps} />);
    expect(screen.getByText('Upload document')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Upload' })).toBeDisabled();
  });

  it('enables button when a file is selected', () => {
    render(<ThirdPartyPortalDocumentUpload {...defaultProps} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['test'], 'test.pdf', { type: 'application/pdf' });
    fireEvent.change(input, { target: { files: [file] } });
    expect(screen.getByRole('button', { name: 'Upload' })).not.toBeDisabled();
  });

  it('calls uploadFn on submit and shows success message', async () => {
    const uploadFn = vi.fn().mockResolvedValue({});
    const onUploaded = vi.fn();
    render(
      <ThirdPartyPortalDocumentUpload
        claimId="CLM-1"
        onUploaded={onUploaded}
        uploadFn={uploadFn}
      />
    );

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['test'], 'test.pdf', { type: 'application/pdf' });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));

    await waitFor(() => {
      expect(uploadFn).toHaveBeenCalledWith('CLM-1', file);
      expect(onUploaded).toHaveBeenCalled();
      expect(screen.getByText('Document uploaded successfully.')).toBeInTheDocument();
    });
  });

  it('shows error message on upload failure', async () => {
    const uploadFn = vi.fn().mockRejectedValue(new Error('Network error'));
    render(
      <ThirdPartyPortalDocumentUpload
        claimId="CLM-1"
        onUploaded={vi.fn()}
        uploadFn={uploadFn}
      />
    );

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['x'], 'x.pdf')] } });
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));

    await waitFor(() => {
      expect(screen.getByText('Error: Network error')).toBeInTheDocument();
    });
  });

  it('shows generic error for non-Error throws', async () => {
    const uploadFn = vi.fn().mockRejectedValue('unknown');
    render(
      <ThirdPartyPortalDocumentUpload
        claimId="CLM-1"
        onUploaded={vi.fn()}
        uploadFn={uploadFn}
      />
    );

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['x'], 'x.pdf')] } });
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));

    await waitFor(() => {
      expect(screen.getByText('Error: Upload failed')).toBeInTheDocument();
    });
  });
});
