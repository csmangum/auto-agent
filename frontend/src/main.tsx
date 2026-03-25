import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import { RoleSimulationProvider } from './context/RoleSimulationContext';
import { Toaster } from 'sonner';
import './index.css';
import App from './App';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: false },
  },
});

const root = document.getElementById('root');
if (!root) throw new Error('Root element not found');

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RoleSimulationProvider>
          <BrowserRouter>
            <App />
            <Toaster theme="dark" position="top-right" richColors closeButton />
          </BrowserRouter>
        </RoleSimulationProvider>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>
);
