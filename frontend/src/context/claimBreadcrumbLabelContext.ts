import { createContext } from 'react';

export const ClaimBreadcrumbLabelContext = createContext<{
  label: string | null;
  setLabel: (value: string | null) => void;
} | null>(null);
