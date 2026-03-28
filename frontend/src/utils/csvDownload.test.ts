import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { downloadCsv } from './csvDownload';

describe('downloadCsv', () => {
  let createObjectURL: ReturnType<typeof vi.spyOn>;
  let revokeObjectURL: ReturnType<typeof vi.spyOn>;
  let clickSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('creates a UTF-8 CSV blob, triggers download, and revokes the URL', () => {
    downloadCsv('report', [
      ['a', 'b'],
      ['1', '2'],
    ]);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls.at(-1)![0] as Blob;
    expect(blob.type).toBe('text/csv;charset=utf-8');
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock');
  });

  it('appends .csv when filename has no extension', () => {
    let capturedDownload = '';
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = document.implementation.createHTMLDocument('').createElement(tag);
      if (tag === 'a') {
        Object.defineProperty(el, 'download', {
          set(v: string) {
            capturedDownload = v;
          },
          get() {
            return capturedDownload;
          },
          configurable: true,
        });
      }
      return el as HTMLAnchorElement;
    });
    downloadCsv('my-export', [['x']]);
    expect(capturedDownload).toBe('my-export.csv');
  });

  it('keeps .csv suffix when already present', () => {
    let capturedDownload = '';
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = document.implementation.createHTMLDocument('').createElement(tag);
      if (tag === 'a') {
        Object.defineProperty(el, 'download', {
          set(v: string) {
            capturedDownload = v;
          },
          get() {
            return capturedDownload;
          },
          configurable: true,
        });
      }
      return el as HTMLAnchorElement;
    });
    downloadCsv('data.csv', [['x']]);
    expect(capturedDownload).toBe('data.csv');
  });

  it('quotes cells that contain comma, quote, or newline', async () => {
    downloadCsv('q', [['a,b', 'say "hi"', 'line1\nline2']]);
    const blob = createObjectURL.mock.calls.at(-1)![0] as Blob;
    const buf = await new Promise<ArrayBuffer>((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(r.result as ArrayBuffer);
      r.onerror = () => reject(r.error);
      r.readAsArrayBuffer(blob);
    });
    const bytes = new Uint8Array(buf);
    expect(bytes[0]).toBe(0xef);
    expect(bytes[1]).toBe(0xbb);
    expect(bytes[2]).toBe(0xbf);
    const body = new TextDecoder('utf-8').decode(bytes.subarray(3));
    expect(body).toContain('"a,b"');
    expect(body).toContain('"say ""hi"""');
    expect(body).toContain('"line1\nline2"');
  });
});
