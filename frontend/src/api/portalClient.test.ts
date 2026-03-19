import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getPortalSession,
  setPortalSession,
  clearPortalSession,
} from './portalClient';

describe('portalClient session helpers', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('getPortalSession returns null when empty', () => {
    expect(getPortalSession()).toBeNull();
  });

  it('setPortalSession and getPortalSession round-trip', () => {
    setPortalSession({ token: 'abc123' });
    expect(getPortalSession()).toEqual({ token: 'abc123' });
  });

  it('setPortalSession with policy and vin', () => {
    setPortalSession({
      policyNumber: 'POL-001',
      vin: '1HGBH41JXMN109186',
    });
    expect(getPortalSession()).toEqual({
      policyNumber: 'POL-001',
      vin: '1HGBH41JXMN109186',
    });
  });

  it('clearPortalSession removes session', () => {
    setPortalSession({ token: 'abc123' });
    expect(getPortalSession()).toEqual({ token: 'abc123' });
    clearPortalSession();
    expect(getPortalSession()).toBeNull();
  });

  it('getPortalSession returns null for invalid JSON', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('invalid-json');
    try {
      expect(getPortalSession()).toBeNull();
    } finally {
      spy.mockRestore();
    }
  });
});
