import { test, expect } from '@playwright/test';

test.describe('Smoke tests', () => {
  test('App loads with sidebar', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Claims System', exact: true }).first()).toBeVisible();
  });

  test('Dashboard loads', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('main').getByRole('heading', { name: /Dashboard|Error/ })).toBeVisible({ timeout: 5000 });
  });

  test('Claims list loads', async ({ page }) => {
    await page.goto('/claims');
    await expect(page.locator('main').getByRole('heading', { name: 'Claims', exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('Documentation loads', async ({ page }) => {
    await page.goto('/docs');
    await expect(page.locator('main').getByRole('heading', { name: 'Documentation' })).toBeVisible({ timeout: 5000 });
  });

  test('Skills page loads', async ({ page }) => {
    await page.goto('/skills');
    await expect(page.getByRole('heading', { name: 'Agent Skills' })).toBeVisible({ timeout: 5000 });
  });

  test('System config loads', async ({ page }) => {
    await page.goto('/system');
    await expect(page.getByRole('heading', { name: 'System Configuration' })).toBeVisible({ timeout: 5000 });
  });
});
