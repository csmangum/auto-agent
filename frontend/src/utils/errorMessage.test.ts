import { describe, it, expect } from 'vitest';
import { getErrorMessage } from './errorMessage';

describe('getErrorMessage', () => {
  it('returns message from Error', () => {
    expect(getErrorMessage(new Error('Not found'))).toBe('Not found');
  });

  it('returns trimmed string errors', () => {
    expect(getErrorMessage('oops')).toBe('oops');
    expect(getErrorMessage('  trimmed  ')).toBe('trimmed');
  });

  it('uses fallback for unsupported shapes', () => {
    expect(getErrorMessage('')).toBe('Something went wrong');
    expect(getErrorMessage('   ')).toBe('Something went wrong');
    expect(getErrorMessage(null)).toBe('Something went wrong');
    expect(getErrorMessage(undefined)).toBe('Something went wrong');
    expect(getErrorMessage(42)).toBe('Something went wrong');
  });

  it('reads message from plain objects', () => {
    expect(getErrorMessage({ message: 'API error' })).toBe('API error');
    expect(getErrorMessage({ message: '  spaced  ' })).toBe('spaced');
  });

  it('uses custom fallback when no usable message', () => {
    expect(getErrorMessage(null, 'Custom')).toBe('Custom');
    expect(getErrorMessage({ message: '' }, 'Custom')).toBe('Custom');
  });

  it('uses fallback when Error message is empty or whitespace', () => {
    expect(getErrorMessage(new Error(''))).toBe('Something went wrong');
    expect(getErrorMessage(new Error('   '), 'Fallback')).toBe('Fallback');
  });
});
