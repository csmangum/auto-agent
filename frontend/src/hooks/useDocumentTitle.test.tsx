import { renderHook } from '@testing-library/react';
import { describe, it, expect, afterEach } from 'vitest';
import { useDocumentTitle } from './useDocumentTitle';

describe('useDocumentTitle', () => {
  afterEach(() => {
    document.title = '';
  });

  it('does nothing when title is nullish', () => {
    document.title = 'Original';
    const { unmount } = renderHook(() => useDocumentTitle(null));
    expect(document.title).toBe('Original');
    unmount();
    expect(document.title).toBe('Original');
  });

  it('sets title with suffix and restores on unmount', () => {
    document.title = 'Start';
    const { unmount } = renderHook(() => useDocumentTitle('Claims'));
    expect(document.title).toBe('Claims · Claims System');
    unmount();
    expect(document.title).toBe('Start');
  });

  it('updates when title changes', () => {
    document.title = 'X';
    const { rerender } = renderHook(({ t }: { t: string }) => useDocumentTitle(t), {
      initialProps: { t: 'One' },
    });
    expect(document.title).toBe('One · Claims System');
    rerender({ t: 'Two' });
    expect(document.title).toBe('Two · Claims System');
  });
});
