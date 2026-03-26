import { createContext } from 'react';

export const ClaimDetailTitleContext = createContext<{
  title: string | null;
  setTitle: (t: string | null) => void;
} | null>(null);
