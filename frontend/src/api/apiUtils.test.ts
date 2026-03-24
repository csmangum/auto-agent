import { describe, it, expect } from 'vitest';
import { parseApiError } from './apiUtils';

describe('parseApiError', () => {
  it('returns fallback message for non-JSON text', () => {
    expect(parseApiError(500, 'Internal Server Error')).toBe(
      'API error 500: Internal Server Error'
    );
  });

  it('extracts detail string from JSON body', () => {
    const body = JSON.stringify({ detail: 'Claim not found' });
    expect(parseApiError(404, body)).toBe('Claim not found');
  });

  it('extracts detail array with msg fields', () => {
    const body = JSON.stringify({
      detail: [{ msg: 'field required' }, { msg: 'invalid value' }],
    });
    expect(parseApiError(422, body)).toBe('field required; invalid value');
  });

  it('filters out detail array entries without msg', () => {
    const body = JSON.stringify({
      detail: [{ msg: 'bad input' }, { loc: ['body'] }, { msg: 'too short' }],
    });
    expect(parseApiError(422, body)).toBe('bad input; too short');
  });

  it('falls back when detail array has no msg fields', () => {
    const body = JSON.stringify({ detail: [{ loc: ['body'] }] });
    expect(parseApiError(400, body)).toContain('API error 400');
  });

  it('truncates long non-JSON text to 200 chars', () => {
    const longText = 'x'.repeat(300);
    const result = parseApiError(500, longText);
    expect(result).toBe(`API error 500: ${'x'.repeat(200)}`);
  });
});
