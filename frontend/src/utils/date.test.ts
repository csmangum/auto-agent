import { describe, it, expect } from 'vitest';
import { formatDateTime, formatDate } from './date';

describe('date utils', () => {
  describe('formatDateTime', () => {
    it('formats ISO 8601 string', () => {
      const result = formatDateTime('2025-01-15T10:30:00');
      expect(result).toBeTruthy();
      expect(typeof result).toBe('string');
    });

    it('formats SQLite datetime string', () => {
      const result = formatDateTime('2025-01-15 10:30:00');
      expect(result).toBeTruthy();
      expect(typeof result).toBe('string');
    });

    it('returns null for null', () => {
      expect(formatDateTime(null)).toBeNull();
    });

    it('returns null for undefined', () => {
      expect(formatDateTime(undefined)).toBeNull();
    });

    it('returns null for empty string', () => {
      expect(formatDateTime('')).toBeNull();
    });

    it('returns null for invalid date string', () => {
      expect(formatDateTime('not-a-date')).toBeNull();
    });
  });

  describe('formatDate', () => {
    it('formats valid date string', () => {
      const result = formatDate('2025-01-15 10:30:00');
      expect(result).toBeTruthy();
      expect(typeof result).toBe('string');
    });

    it('returns null for null', () => {
      expect(formatDate(null)).toBeNull();
    });

    it('returns null for undefined', () => {
      expect(formatDate(undefined)).toBeNull();
    });

    it('returns null for invalid date string', () => {
      expect(formatDate('invalid')).toBeNull();
    });
  });
});
