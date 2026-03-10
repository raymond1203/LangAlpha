import React from 'react';
import { render, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

function createWrapper(queryClient, route = '/') {
  return function Wrapper({ children }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>
          {children}
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

export function renderWithProviders(ui, { route = '/', queryClient, ...options } = {}) {
  const client = queryClient || createTestQueryClient();
  const Wrapper = createWrapper(client, route);
  return { ...render(ui, { wrapper: Wrapper, ...options }), queryClient: client };
}

export function renderHookWithProviders(hook, { route = '/', queryClient, ...options } = {}) {
  const client = queryClient || createTestQueryClient();
  const wrapper = createWrapper(client, route);
  return { ...renderHook(hook, { wrapper, ...options }), queryClient: client };
}

export { createTestQueryClient };
