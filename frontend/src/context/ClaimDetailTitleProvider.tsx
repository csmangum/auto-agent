import { useMemo, useState, type ReactNode } from 'react';
import { ClaimDetailTitleContext } from './claimDetailTitleContext';

export default function ClaimDetailTitleProvider({ children }: { children: ReactNode }) {
  const [title, setTitle] = useState<string | null>(null);
  const value = useMemo(() => ({ title, setTitle }), [title]);
  return (
    <ClaimDetailTitleContext.Provider value={value}>
      {children}
    </ClaimDetailTitleContext.Provider>
  );
}
