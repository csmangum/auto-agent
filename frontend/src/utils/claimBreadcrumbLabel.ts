import type { Claim } from '../api/types';

/** Short label for breadcrumbs and browser tab (policy + optional vehicle). */
export function formatClaimBreadcrumbLabel(claim: Claim): string {
  const policy = claim.policy_number?.trim() || claim.id;
  const vehicleParts = [
    claim.vehicle_year != null ? String(claim.vehicle_year) : '',
    claim.vehicle_make?.trim(),
    claim.vehicle_model?.trim(),
  ].filter(Boolean);
  const vehicle = vehicleParts.join(' ');
  if (vehicle) return `${policy} · ${vehicle}`;
  return policy;
}
