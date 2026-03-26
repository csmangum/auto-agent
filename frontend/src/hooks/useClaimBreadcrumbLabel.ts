import { useContext } from 'react';
import { ClaimBreadcrumbLabelContext } from '../context/claimBreadcrumbLabelContext';

export function useSetClaimBreadcrumbLabel() {
  const ctx = useContext(ClaimBreadcrumbLabelContext);
  return ctx?.setLabel ?? (() => {});
}

export function useClaimBreadcrumbLabel() {
  return useContext(ClaimBreadcrumbLabelContext)?.label ?? null;
}
