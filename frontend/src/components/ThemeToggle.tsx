import { useTheme, type ThemeMode } from '../context/ThemeContext';

function SunIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="4" strokeWidth={2} />
      <path
        strokeLinecap="round"
        strokeWidth={2}
        d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"
      />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"
      />
    </svg>
  );
}

function SystemIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="2" y="3" width="20" height="14" rx="2" strokeWidth={2} />
      <path strokeLinecap="round" strokeWidth={2} d="M8 21h8M12 17v4" />
    </svg>
  );
}

interface ThemeOption {
  mode: ThemeMode;
  label: string;
  Icon: () => JSX.Element;
}

const THEME_OPTIONS: ThemeOption[] = [
  { mode: 'light', label: 'Light', Icon: SunIcon },
  { mode: 'system', label: 'System', Icon: SystemIcon },
  { mode: 'dark', label: 'Dark', Icon: MoonIcon },
];

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div
      className="flex items-center gap-0.5 p-0.5 rounded-lg bg-gray-800 ring-1 ring-gray-700"
      role="group"
      aria-label="Theme"
    >
      {THEME_OPTIONS.map(({ mode, label, Icon }) => (
        <button
          key={mode}
          type="button"
          onClick={() => setTheme(mode)}
          title={`${label} theme`}
          aria-label={`${label} theme`}
          aria-pressed={theme === mode}
          className={`flex-1 flex items-center justify-center p-1.5 rounded-md transition-all duration-150 ${
            theme === mode
              ? 'bg-gray-600 text-gray-100 shadow-sm'
              : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          <Icon />
        </button>
      ))}
    </div>
  );
}
