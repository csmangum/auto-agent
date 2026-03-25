import { describe, it, expect } from 'vitest';
import { getErrorMessage } from './errorMessage';

describe('getErrorMessage', () => {
  it('returns message from Error', () => {
    expect(getErrorMessage(new Error('Not found'))).toBe('Not found');
  });

  it('uses fallback for non-Error', () => {
    expect(getErrorMessage('oops')).toBe('Something went wrong');
    expect(getErrorMessage(null)).toBe('Something went wrong');
    expect(getErrorMessage(undefined)).toBe('Something went wrong');
    expect(getErrorMessage(42)).toBe('Something went wrong');
  });

  it('uses custom fallback', () => {
    expect(getErrorMessage('x', 'Custom')).toBe('Custom');
  });

  it('uses fallback when Error message is empty or whitespace', () => {
    expect(getErrorMessage(new Error(''))).toBe('Something went wrong');
    expect(getErrorMessage(new Error('   '), 'Fallback')).toBe('Fallback');
  });
});
