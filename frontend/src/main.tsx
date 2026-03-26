import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import { RoleSimulationProvider } from './context/RoleSimulationContext';
import { ThemeProvider } from './context/ThemeContext';
import AppToaster from './components/AppToaster';
import ErrorBoundary from './components/ErrorBoundary';
import { initSentry } from './lib/sentry';
import './index.css';
import App from './App';

initSentry();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: false },
  },
});

const root = document.getElementById('root');
if (!root) throw new Error('Root element not found');

createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RoleSimulationProvider>
            <BrowserRouter>
              <ErrorBoundary>
                <App />
                <AppToaster />
              </ErrorBoundary>
            </BrowserRouter>
          </RoleSimulationProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>
);
