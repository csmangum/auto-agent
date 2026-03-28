import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { ThemeProvider } from '../context/ThemeContext';
import AppToaster from './AppToaster';

vi.mock('sonner', () => ({
  Toaster: (props: { theme?: string; position?: string }) => (
    <div
      data-testid="mock-toaster"
      data-theme={props.theme}
      data-position={props.position}
    />
  ),
}));

describe('AppToaster', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove('dark');
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    });
  });

  it('passes resolved theme and layout props to Sonner Toaster', () => {
    render(
      <ThemeProvider>
        <AppToaster />
      </ThemeProvider>
    );
    const toaster = screen.getByTestId('mock-toaster');
    expect(toaster).toHaveAttribute('data-theme', 'light');
    expect(toaster).toHaveAttribute('data-position', 'top-right');
  });
});
