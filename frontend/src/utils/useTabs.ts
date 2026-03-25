import { useCallback, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * URL-synced tab state via the `tab` search param.
 *
 * @param validTabs - ordered list of allowed tab keys
 * @param defaultTab - the tab shown when the param is absent or invalid
 */
export function useTabs<T extends string>(
  validTabs: readonly T[],
  defaultTab: T,
): [T, (tab: T) => void] {
  const [searchParams, setSearchParams] = useSearchParams();

  const raw = searchParams.get('tab') as T | null;
  const activeTab: T =
    raw !== null && (validTabs as readonly string[]).includes(raw) ? raw : defaultTab;

  // Drop invalid `tab` so the URL matches the rendered panel (default when unknown).
  useEffect(() => {
    if (raw === null) return;
    if ((validTabs as readonly string[]).includes(raw)) return;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('tab');
        return next;
      },
      { replace: true },
    );
  }, [raw, setSearchParams, validTabs]);

  const setActiveTab = useCallback(
    (tab: T) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('tab', tab);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return [activeTab, setActiveTab];
}
