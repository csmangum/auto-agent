/** Shared claim priority constants for review queue, workbench, assignment queue. */

export const CLAIM_PRIORITY_ORDER = ['critical', 'high', 'medium', 'low'] as const;

export const CLAIM_PRIORITY_RANK: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

export const CLAIM_PRIORITY_STYLES: Record<
  string,
  { bg: string; text: string; icon: string }
> = {
  critical: { bg: 'bg-red-500/20', text: 'text-red-400', icon: '🔴' },
  high: { bg: 'bg-orange-500/20', text: 'text-orange-400', icon: '🟠' },
  medium: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', icon: '🟡' },
  low: { bg: 'bg-gray-500/20', text: 'text-gray-400', icon: '⚪' },
};
