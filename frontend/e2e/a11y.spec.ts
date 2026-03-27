/**
 * Accessibility audit tests using @axe-core/playwright.
 *
 * Unlike the vitest unit tests with jest-axe (src/components/a11y.test.tsx),
 * these tests run against a fully-built Vite dev server with real CSS—including
 * Tailwind custom properties—so color-contrast rules are evaluated correctly.
 *
 * Subset of pages chosen to cover the main navigation routes without
 * requiring authenticated sessions or backend data (API calls return mock
 * or empty-state responses which is sufficient for structural a11y).
 *
 * Run locally:  npm run test:a11y
 * CI:           npm run test:a11y  (Playwright spins up Vite dev server)
 */
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const CRITICAL_PAGES = [
  { name: 'Dashboard',        path: '/dashboard' },
  { name: 'Claims list',      path: '/claims' },
  { name: 'New Claim form',   path: '/claims/new' },
  { name: 'Documentation',    path: '/docs' },
  { name: 'System config',    path: '/system' },
] as const;

// Tags whose rules are fully supported when real CSS is available.
// 'wcag2a', 'wcag2aa' and 'wcag21aa' cover SC 1.4.3 / 1.4.11
// (color-contrast and non-text contrast).
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa'] as const;

// Rules that produce false positives in the dev/mock environment (e.g. a rule
// that fires on mock data or placeholder content). Add rule IDs here when
// confirmed false positives; document the reason alongside each entry.
const EXCLUDED_RULES: string[] = [];

test.describe('a11y: full-CSS audit (Playwright + axe)', () => {
  for (const { name, path } of CRITICAL_PAGES) {
    test(`${name} – no axe violations (color-contrast included)`, async ({ page }) => {
      await page.goto(path);

      // Wait for the page to settle (sidebar/main content rendered).
      await page.waitForLoadState('networkidle');

      const results = await new AxeBuilder({ page })
        .withTags([...AXE_TAGS])
        .disableRules(EXCLUDED_RULES)
        .analyze();

      expect(results.violations).toEqual([]);
    });
  }
});
