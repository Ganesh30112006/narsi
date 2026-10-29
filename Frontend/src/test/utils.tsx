import type { ReactElement } from 'react';
import { render } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/providers/AppProviders';
import { routes } from '../app/router';
import { MOCK_PASSWORD } from '../mocks/mockDb';
import { authApi } from '../services/authApi';

/** Starts a mock-backend administrator session (as if the HTTP-only cookie were set). */
export async function signInAsAdmin() {
  return authApi.login({ username: 'admin', password: MOCK_PASSWORD });
}

/** Renders the full application route table at `path`. */
export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const result = render(
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { ...result, router };
}

/** Renders a component with providers and a router context. */
export function renderWithProviders(ui: ReactElement, { path = '/' }: { path?: string } = {}) {
  return render(
    <AppProviders>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </AppProviders>,
  );
}
