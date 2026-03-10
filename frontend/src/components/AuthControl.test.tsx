import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from '../context/AuthContext';
import AuthControl from './AuthControl';

function renderWithProviders() {
  return render(
    <BrowserRouter>
      <AuthProvider>
        <AuthControl />
      </AuthProvider>
    </BrowserRouter>
  );
}

describe('AuthControl', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('shows Set API key button when not authenticated', () => {
    renderWithProviders();
    expect(screen.getByRole('button', { name: /set api key/i })).toBeInTheDocument();
  });

  it('shows form when Set API key is clicked', () => {
    renderWithProviders();
    fireEvent.click(screen.getByRole('button', { name: /set api key/i }));
    expect(screen.getByPlaceholderText('API key')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Set' })).toBeInTheDocument();
  });

  it('submits and authenticates when valid key entered', () => {
    renderWithProviders();
    fireEvent.click(screen.getByRole('button', { name: /set api key/i }));
    fireEvent.change(screen.getByPlaceholderText('API key'), { target: { value: 'my-secret-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Set' }));
    expect(screen.getByText('Key set')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /clear key/i })).toBeInTheDocument();
  });

  it('does not submit empty key', () => {
    renderWithProviders();
    fireEvent.click(screen.getByRole('button', { name: /set api key/i }));
    fireEvent.change(screen.getByPlaceholderText('API key'), { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Set' }));
    expect(screen.getByPlaceholderText('API key')).toBeInTheDocument();
  });

  it('cancel button closes form', () => {
    renderWithProviders();
    fireEvent.click(screen.getByRole('button', { name: /set api key/i }));
    fireEvent.click(screen.getByRole('button', { name: '✕' }));
    expect(screen.queryByPlaceholderText('API key')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /set api key/i })).toBeInTheDocument();
  });

  it('Clear key logs out', () => {
    renderWithProviders();
    fireEvent.click(screen.getByRole('button', { name: /set api key/i }));
    fireEvent.change(screen.getByPlaceholderText('API key'), { target: { value: 'key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Set' }));
    fireEvent.click(screen.getByRole('button', { name: /clear key/i }));
    expect(screen.getByRole('button', { name: /set api key/i })).toBeInTheDocument();
  });
});
