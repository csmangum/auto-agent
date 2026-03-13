/**
 * Shared accent colors and theme utilities for simulation and stat components.
 */

export type SimulationAccent = 'emerald' | 'amber' | 'purple';

export type QuickStatAccent =
  | 'emerald'
  | 'blue'
  | 'green'
  | 'amber'
  | 'teal'
  | 'purple'
  | 'indigo'
  | 'red';

/** MessagesTab color classes by accent */
export interface MessagesTabColors {
  text: string;
  hover: string;
  bg: string;
  hoverBg: string;
  ring: string;
  resultBg: string;
  resultText: string;
  borderBg: string;
  borderColor: string;
  statusBg: string;
  statusText: string;
}

export const MESSAGES_TAB_COLORS: Record<SimulationAccent, MessagesTabColors> = {
  emerald: {
    text: 'text-emerald-400',
    hover: 'hover:text-emerald-300',
    bg: 'bg-emerald-600',
    hoverBg: 'hover:bg-emerald-500',
    ring: 'focus:ring-emerald-500/40',
    resultBg: 'bg-emerald-500/10',
    resultText: 'text-emerald-400',
    borderBg: 'bg-emerald-500/5',
    borderColor: 'border-emerald-500/10',
    statusBg: 'bg-emerald-500/20',
    statusText: 'text-emerald-400',
  },
  amber: {
    text: 'text-amber-400',
    hover: 'hover:text-amber-300',
    bg: 'bg-amber-600',
    hoverBg: 'hover:bg-amber-500',
    ring: 'focus:ring-amber-500/40',
    resultBg: 'bg-amber-500/10',
    resultText: 'text-amber-400',
    borderBg: 'bg-amber-500/5',
    borderColor: 'border-amber-500/10',
    statusBg: 'bg-amber-500/20',
    statusText: 'text-amber-400',
  },
  purple: {
    text: 'text-purple-400',
    hover: 'hover:text-purple-300',
    bg: 'bg-purple-600',
    hoverBg: 'hover:bg-purple-500',
    ring: 'focus:ring-purple-500/40',
    resultBg: 'bg-purple-500/10',
    resultText: 'text-purple-400',
    borderBg: 'bg-purple-500/5',
    borderColor: 'border-purple-500/10',
    statusBg: 'bg-purple-500/20',
    statusText: 'text-purple-400',
  },
};

/** SimulationBanner accent styles */
export const BANNER_ACCENT_STYLES: Record<SimulationAccent, string> = {
  emerald: 'bg-emerald-600/10 border-emerald-500/30 text-emerald-400',
  amber: 'bg-amber-600/10 border-amber-500/30 text-amber-400',
  purple: 'bg-purple-600/10 border-purple-500/30 text-purple-400',
};

/** RoleSelectLanding accent map */
export const ROLE_SELECT_ACCENT_MAP: Record<
  SimulationAccent,
  { card: string; hover: string; border: string }
> = {
  emerald: {
    card: 'hover:bg-emerald-600/5',
    hover: 'group-hover:text-emerald-400',
    border: 'hover:border-emerald-500/30',
  },
  amber: {
    card: 'hover:bg-amber-600/5',
    hover: 'group-hover:text-amber-400',
    border: 'hover:border-amber-500/30',
  },
  purple: {
    card: 'hover:bg-purple-600/5',
    hover: 'group-hover:text-purple-400',
    border: 'hover:border-purple-500/30',
  },
};

/** QuickStat text color by accent */
export const QUICK_STAT_COLOR_MAP: Record<QuickStatAccent, string> = {
  emerald: 'text-emerald-400',
  blue: 'text-blue-400',
  green: 'text-green-400',
  amber: 'text-amber-400',
  teal: 'text-teal-400',
  purple: 'text-purple-400',
  indigo: 'text-indigo-400',
  red: 'text-red-400',
};
