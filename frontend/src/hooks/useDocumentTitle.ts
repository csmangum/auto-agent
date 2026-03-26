import { useEffect } from 'react';

const BASE = 'Claims System';

export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    if (!title) return;
    const prev = document.title;
    document.title = `${title} · ${BASE}`;
    return () => {
      document.title = prev;
    };
  }, [title]);
}
