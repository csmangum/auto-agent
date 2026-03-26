import { useMemo, useState, type ReactNode } from 'react';
import { ClaimBreadcrumbLabelContext } from './claimBreadcrumbLabelContext';

export default function ClaimBreadcrumbLabelProvider({ children }: { children: ReactNode }) {
  const [label, setLabel] = useState<string | null>(null);
  const value = useMemo(() => ({ label, setLabel }), [label]);
  return (
    <ClaimBreadcrumbLabelContext.Provider value={value}>
      {children}
    </ClaimBreadcrumbLabelContext.Provider>
  );
}
