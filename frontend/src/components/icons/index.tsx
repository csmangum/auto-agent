import type { SVGProps } from 'react';

const strokeProps = {
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  fill: 'none',
};

function IconWrapper({
  children,
  className,
  ...rest
}: SVGProps<SVGSVGElement> & { children: React.ReactNode }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      stroke="currentColor"
      className={className}
      {...strokeProps}
      {...rest}
    >
      {children}
    </svg>
  );
}

/** Dashboard / bar chart */
export function DashboardIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M3 3v18h18" />
      <path d="M7 16v-6" />
      <path d="M12 16v-4" />
      <path d="M17 16v-10" />
    </IconWrapper>
  );
}

/** Claims list / clipboard */
export function ClaimsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2" />
      <path d="M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
      <path d="M9 12h6" />
      <path d="M9 16h6" />
    </IconWrapper>
  );
}

/** New / plus */
export function PlusIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </IconWrapper>
  );
}

/** Documentation / book */
export function DocsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
      <path d="M8 7h8" />
      <path d="M8 11h8" />
    </IconWrapper>
  );
}

/** Skills / brain */
export function SkillsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M9.5 10.5A2.5 2.5 0 1112 8" />
      <path d="M14.5 10.5a2.5 2.5 0 10-2.5-2.5" />
      <path d="M12 18a6 6 0 005.2-9 6 6 0 00-10.4 0A6 6 0 0012 18z" />
      <path d="M12 2a10 10 0 109.17 5.5" />
    </IconWrapper>
  );
}

/** Agents & crews / people */
export function AgentsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 00-3-3.87" />
      <path d="M16 3.13a4 4 0 010 7.75" />
    </IconWrapper>
  );
}

/** System config / gear */
export function SystemIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 1v2" />
      <path d="M12 21v2" />
      <path d="M4.22 4.22l1.42 1.42" />
      <path d="M18.36 18.36l1.42 1.42" />
      <path d="M1 12h2" />
      <path d="M21 12h2" />
      <path d="M4.22 19.78l1.42-1.42" />
      <path d="M18.36 5.64l1.42-1.42" />
    </IconWrapper>
  );
}

/** Core routing / split path */
export function RouterIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M12 3v7" />
      <path d="M7 21l5-11" />
      <path d="M17 21l-5-11" />
    </IconWrapper>
  );
}

/** New claim workflow / document with edit */
export function WorkflowIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <path d="M14 2v6h6" />
      <path d="M10 13l2 2 4-4" />
    </IconWrapper>
  );
}

/** Duplicate detection / search */
export function SearchIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <circle cx="11" cy="11" r="8" />
      <path d="M21 21l-4.35-4.35" />
    </IconWrapper>
  );
}

/** Fraud detection / shield alert */
export function FraudIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <path d="M12 8v4" />
      <path d="M12 16h.01" />
    </IconWrapper>
  );
}

/** Total loss / bolt */
export function TotalLossIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
    </IconWrapper>
  );
}

/** Partial loss / wrench */
export function PartialLossIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
    </IconWrapper>
  );
}

/** Escalation / alert triangle */
export function EscalationIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </IconWrapper>
  );
}

/** Settlement workflow – document with check (closure) */
export function SettlementIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <path d="M14 2v6h6" />
      <path d="M9 15l2 2 4-4" />
    </IconWrapper>
  );
}

/** Subrogation – recovery / follow-up (arrow loop) */
export function SubrogationIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M21 12a9 9 0 11-9-9" />
      <path d="M21 3v6h-6" />
    </IconWrapper>
  );
}

/** Default / document */
export function DocumentIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <path d="M14 2v6h6" />
      <path d="M16 13H8" />
      <path d="M16 17H8" />
      <path d="M10 9H8" />
    </IconWrapper>
  );
}

/** Warning (for error states) */
export function WarningIcon(props: SVGProps<SVGSVGElement>) {
  return <EscalationIcon {...props} />;
}

/** Bell (notifications / human-in-the-loop) */
export function BellIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 01-3.46 0" />
    </IconWrapper>
  );
}

/** Currency / valuation */
export function CurrencyIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <circle cx="12" cy="12" r="10" />
      <path d="M16 8h-2a2 2 0 00-2 2v0a2 2 0 002 2h2a2 2 0 012 2v0a2 2 0 01-2 2h-2a2 2 0 00-2 2v0a2 2 0 002 2h2" />
    </IconWrapper>
  );
}

/** Token / budget (stacked) */
export function TokenIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M6 8h12" />
      <path d="M6 12h12" />
      <path d="M6 16h12" />
    </IconWrapper>
  );
}

/** AI / sparkle (generate with AI) */
export function SparkleIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z" />
      <path d="M5 17l.75 1.5 1.5.75-1.5.75L5 21.5l-.75-1.5-1.5-.75 1.5-.75L5 17z" />
      <path d="M19 17l.75 1.5 1.5.75-1.5.75L19 21.5l-.75-1.5-1.5-.75 1.5-.75L19 17z" />
    </IconWrapper>
  );
}

/** Workbench / tool board */
export function WorkbenchIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M3 21h18" />
      <path d="M5 21V7l7-4 7 4v14" />
      <path d="M9 21v-6h6v6" />
      <path d="M10 10h4" />
    </IconWrapper>
  );
}

/** Queue / inbox tray */
export function QueueIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M22 12h-6l-2 3h-4l-2-3H2" />
      <path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z" />
    </IconWrapper>
  );
}

/** Diary / calendar */
export function DiaryIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <path d="M16 2v4" />
      <path d="M8 2v4" />
      <path d="M3 10h18" />
      <path d="M8 14h.01" />
      <path d="M12 14h.01" />
      <path d="M16 14h.01" />
      <path d="M8 18h.01" />
      <path d="M12 18h.01" />
    </IconWrapper>
  );
}

/** Simulation / role play (theater masks) */
export function SimulationIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconWrapper {...props}>
      <path d="M9 3C5.69 3 3 5.69 3 9c0 2.02 1 3.81 2.53 4.9A5.99 5.99 0 003 18v1h12v-1a5.99 5.99 0 00-2.53-4.1A5.98 5.98 0 0015 9c0-3.31-2.69-6-6-6z" />
      <circle cx="7" cy="8" r="1" />
      <circle cx="11" cy="8" r="1" />
      <path d="M7 11s1 1.5 2 1.5S11 11 11 11" />
      <path d="M15 7c2.76 0 5 2.24 5 5 0 1.68-.83 3.16-2.1 4.07A4.99 4.99 0 0120 20v1h-7" />
      <circle cx="16" cy="11" r="0.75" />
      <circle cx="19" cy="11" r="0.75" />
      <path d="M16 13.5s.75-1 1.5-1 1.5 1 1.5 1" />
    </IconWrapper>
  );
}
