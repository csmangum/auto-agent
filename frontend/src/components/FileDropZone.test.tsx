import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import FileDropZone from './FileDropZone';

function makeFile(name: string, type: string, size = 100): File {
  const blob = new Blob(['x'.repeat(size)], { type });
  return new File([blob], name, { type });
}

describe('FileDropZone', () => {
  const onFilesSelected = vi.fn();
  const onValidationError = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders children and a file input', () => {
    render(
      <FileDropZone onFilesSelected={onFilesSelected}>
        <span>Drop here</span>
      </FileDropZone>
    );
    expect(screen.getByText('Drop here')).toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeInTheDocument();
  });

  describe('wildcard MIME accept (image/*)', () => {
    it('accepts image/png when accept="image/*"', () => {
      render(
        <FileDropZone accept="image/*" onFilesSelected={onFilesSelected} onValidationError={onValidationError}>
          <span>Drop</span>
        </FileDropZone>
      );
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = makeFile('photo.png', 'image/png');
      fireEvent.change(input, { target: { files: [file] } });
      expect(onFilesSelected).toHaveBeenCalledWith([file]);
      expect(onValidationError).not.toHaveBeenCalled();
    });

    it('accepts image/jpeg when accept="image/*"', () => {
      render(
        <FileDropZone accept="image/*" onFilesSelected={onFilesSelected} onValidationError={onValidationError}>
          <span>Drop</span>
        </FileDropZone>
      );
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = makeFile('photo.jpg', 'image/jpeg');
      fireEvent.change(input, { target: { files: [file] } });
      expect(onFilesSelected).toHaveBeenCalledWith([file]);
    });

    it('rejects application/pdf when accept="image/*"', () => {
      render(
        <FileDropZone accept="image/*" onFilesSelected={onFilesSelected} onValidationError={onValidationError}>
          <span>Drop</span>
        </FileDropZone>
      );
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = makeFile('doc.pdf', 'application/pdf');
      fireEvent.change(input, { target: { files: [file] } });
      expect(onFilesSelected).not.toHaveBeenCalled();
      expect(onValidationError).toHaveBeenCalledWith(expect.stringContaining('doc.pdf'));
    });
  });

  describe('extension accept (.pdf)', () => {
    it('accepts .pdf by extension', () => {
      render(
        <FileDropZone accept=".pdf" onFilesSelected={onFilesSelected} onValidationError={onValidationError}>
          <span>Drop</span>
        </FileDropZone>
      );
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = makeFile('report.pdf', 'application/pdf');
      fireEvent.change(input, { target: { files: [file] } });
      expect(onFilesSelected).toHaveBeenCalledWith([file]);
    });

    it('rejects .png when accept=".pdf"', () => {
      render(
        <FileDropZone accept=".pdf" onFilesSelected={onFilesSelected} onValidationError={onValidationError}>
          <span>Drop</span>
        </FileDropZone>
      );
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = makeFile('photo.png', 'image/png');
      fireEvent.change(input, { target: { files: [file] } });
      expect(onFilesSelected).not.toHaveBeenCalled();
      expect(onValidationError).toHaveBeenCalledWith(expect.stringContaining('photo.png'));
    });

    it('accepts mixed accept list (image/*,.pdf)', () => {
      render(
        <FileDropZone accept="image/*,.pdf" onFilesSelected={onFilesSelected} onValidationError={onValidationError}>
          <span>Drop</span>
        </FileDropZone>
      );
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const png = makeFile('photo.png', 'image/png');
      const pdf = makeFile('doc.pdf', 'application/pdf');
      fireEvent.change(input, { target: { files: [png, pdf] } });
      expect(onFilesSelected).toHaveBeenCalledWith([png, pdf]);
    });
  });

  describe('maxBytes validation', () => {
    it('accepts file within maxBytes', () => {
      render(
        <FileDropZone accept="image/*" maxBytes={200} onFilesSelected={onFilesSelected} onValidationError={onValidationError}>
          <span>Drop</span>
        </FileDropZone>
      );
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = makeFile('small.png', 'image/png', 100);
      fireEvent.change(input, { target: { files: [file] } });
      expect(onFilesSelected).toHaveBeenCalledWith([file]);
    });

    it('rejects file exceeding maxBytes', () => {
      render(
        <FileDropZone accept="image/*" maxBytes={50} onFilesSelected={onFilesSelected} onValidationError={onValidationError}>
          <span>Drop</span>
        </FileDropZone>
      );
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = makeFile('big.png', 'image/png', 200);
      fireEvent.change(input, { target: { files: [file] } });
      expect(onFilesSelected).not.toHaveBeenCalled();
      expect(onValidationError).toHaveBeenCalledWith(expect.stringContaining('big.png'));
    });

    it('uses maxBytesLabel in error message when provided', () => {
      render(
        <FileDropZone
          accept="image/*"
          maxBytes={50}
          maxBytesLabel="50 bytes"
          onFilesSelected={onFilesSelected}
          onValidationError={onValidationError}
        >
          <span>Drop</span>
        </FileDropZone>
      );
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = makeFile('big.png', 'image/png', 200);
      fireEvent.change(input, { target: { files: [file] } });
      expect(onValidationError).toHaveBeenCalledWith(expect.stringContaining('50 bytes'));
    });
  });

  describe('disabled behavior', () => {
    it('does not call onFilesSelected when disabled and file dropped', () => {
      render(
        <FileDropZone disabled accept="image/*" onFilesSelected={onFilesSelected} onValidationError={onValidationError}>
          <span>Drop</span>
        </FileDropZone>
      );
      const label = document.querySelector('label') as HTMLLabelElement;
      const file = makeFile('photo.png', 'image/png');
      const dt = { files: [file], types: ['Files'] } as unknown as DataTransfer;
      fireEvent.drop(label, { dataTransfer: dt });
      expect(onFilesSelected).not.toHaveBeenCalled();
    });
  });
});
