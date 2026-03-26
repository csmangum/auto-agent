import { useContext } from 'react';
import { ClaimDetailTitleContext } from '../context/claimDetailTitleContext';

export function useClaimDetailTitleSetter() {
  const ctx = useContext(ClaimDetailTitleContext);
  return ctx?.setTitle ?? (() => {});
}

export function useClaimDetailTitleForBreadcrumb() {
  return useContext(ClaimDetailTitleContext)?.title ?? null;
}
