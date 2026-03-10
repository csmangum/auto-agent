import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AuthProvider, useAuth } from './AuthContext';

const TestConsumer = () => {
  const { isAuthenticated, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="auth-status">{isAuthenticated ? 'authenticated' : 'anonymous'}</span>
      {!isAuthenticated && (
        <button onClick={() => login('test-token')}>Login</button>
      )}
      {isAuthenticated && (
        <button onClick={logout}>Logout</button>
      )}
    </div>
  );
};

describe('AuthContext', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('provides anonymous state by default', () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );
    expect(screen.getByTestId('auth-status')).toHaveTextContent('anonymous');
  });

  it('login updates state and stores token', () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );
    fireEvent.click(screen.getByRole('button', { name: 'Login' }));
    expect(screen.getByTestId('auth-status')).toHaveTextContent('authenticated');
    expect(localStorage.getItem('claims_api_token')).toBe('test-token');
  });

  it('logout clears state and token', () => {
    localStorage.setItem('claims_api_token', 'test-token');
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );
    expect(screen.getByTestId('auth-status')).toHaveTextContent('authenticated');
    fireEvent.click(screen.getByRole('button', { name: 'Logout' }));
    expect(screen.getByTestId('auth-status')).toHaveTextContent('anonymous');
    expect(localStorage.getItem('claims_api_token')).toBeNull();
  });

  it('useAuth throws when used outside AuthProvider', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() =>
      render(
        <TestConsumer />
      )
    ).toThrow('useAuth must be used within AuthProvider');
    consoleSpy.mockRestore();
  });
});
