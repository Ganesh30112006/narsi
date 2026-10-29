import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { getMockState } from '../mocks/mockTransport';
import { api } from '../services/api';
import type { Transport } from '../services/transport';
import { TransportFailure } from '../services/transport';
import { mockTransport } from '../mocks/mockTransport';
import { renderApp, signInAsAdmin } from '../test/utils';

/** Wraps the mock backend, failing requests whose path matches. */
function failPaths(pattern: RegExp, failure: 'network' | 500 | 403): Transport {
  return async (request) => {
    if (pattern.test(request.path)) {
      if (failure === 'network') throw new TransportFailure('network');
      return { status: failure, headers: {}, body: { detail: 'boom' } };
    }
    return mockTransport(request);
  };
}

afterEach(() => api.setTransport(mockTransport));

describe('LoginPage', () => {
  it('validates input before submitting and has no email or password-reset options', async () => {
    renderApp('/admin/login');
    expect(await screen.findByRole('heading', { name: 'Administrator sign in' })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Username'), 'x'.repeat(65));
    await userEvent.type(screen.getByLabelText('Password'), 'x');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Usernames are at most 64 characters.')).toBeInTheDocument();
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/forgot/i)).not.toBeInTheDocument();
  });

  it('shows a clear message for invalid credentials and clears the password', async () => {
    renderApp('/admin/login');
    await userEvent.type(await screen.findByLabelText('Username'), 'admin');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong-password');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Incorrect username or password.')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toHaveValue('');
  });

  it('toggles password visibility', async () => {
    renderApp('/admin/login');
    const password = await screen.findByLabelText('Password');
    expect(password).toHaveAttribute('type', 'password');
    await userEvent.click(screen.getByRole('button', { name: 'Show password' }));
    expect(password).toHaveAttribute('type', 'text');
  });

  it('signs in and returns to the requested page', async () => {
    const { router } = renderApp('/app/findings');
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/login'));
    await userEvent.type(await screen.findByLabelText('Username'), 'admin');
    await userEvent.type(screen.getByLabelText('Password'), 'GuardDemo#2026');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/app/findings'));
    expect(await screen.findByRole('heading', { name: 'Findings', level: 1 })).toBeInTheDocument();
  });
});

describe('DashboardPage', () => {
  it('shows summary statistics and recent scans', async () => {
    await signInAsAdmin();
    renderApp('/app/dashboard');
    expect(
      await screen.findByRole('heading', { level: 1, name: /Good (morning|afternoon|evening), Ananya/ }),
    ).toBeInTheDocument();
    const summary = await screen.findByRole('list', { name: 'Findings by PII type' });
    expect(summary).toBeInTheDocument();
    expect(screen.getByText('Documents scanned')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Recent scans' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Scan a document' })).toBeInTheDocument();
  });

  it('shows an error with retry instead of empty data when the API fails', async () => {
    await signInAsAdmin();
    api.setTransport(failPaths(/^\/dashboard/, 500));
    renderApp('/app/dashboard');
    expect(await screen.findByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
    expect(screen.queryByText('No scans yet')).not.toBeInTheDocument();
  });
});

describe('DocumentsPage', () => {
  it('lists documents with actions', async () => {
    await signInAsAdmin();
    renderApp('/app/documents');
    expect(await screen.findByRole('link', { name: 'employee_application.pdf' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Actions for employee_application.pdf' }));
    const menu = screen.getByRole('menu');
    for (const action of ['View', 'Scan again', 'Download', 'Redact', 'Delete']) {
      expect(within(menu).getByRole('menuitem', { name: action })).toBeInTheDocument();
    }
  });

  it('confirms before deleting', async () => {
    await signInAsAdmin();
    renderApp('/app/documents');
    await userEvent.click(await screen.findByRole('button', { name: 'Actions for board_minutes_q2.pdf' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Delete this document?' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete document' }));
    await waitFor(() => expect(screen.queryByRole('link', { name: 'board_minutes_q2.pdf' })).not.toBeInTheDocument());
    expect(getMockState().documents.some((doc) => doc.fileName === 'board_minutes_q2.pdf')).toBe(false);
  });

  it('shows an empty state when there are no documents', async () => {
    await signInAsAdmin();
    getMockState().documents = [];
    renderApp('/app/documents');
    expect(await screen.findByText('No documents yet')).toBeInTheDocument();
    expect(screen.getByText('Upload your first document to begin scanning.')).toBeInTheDocument();
  });

  it('distinguishes a network failure from an empty result', async () => {
    await signInAsAdmin();
    api.setTransport(failPaths(/^\/documents$/, 'network'));
    renderApp('/app/documents');
    expect(await screen.findByText('Unable to connect')).toBeInTheDocument();
    expect(screen.queryByText('No documents yet')).not.toBeInTheDocument();
  });

  it('lists public uploads alongside administrator uploads', async () => {
    await signInAsAdmin();
    renderApp('/app/documents');
    expect((await screen.findAllByText('by Public upload')).length).toBeGreaterThan(0);
  });
});

describe('ScanDetailsPage', () => {
  it('summarises a completed scan', async () => {
    await signInAsAdmin();
    const document = getMockState().documents.find((doc) => doc.fileName === 'employee_application.pdf');
    renderApp(`/app/scans/${document?.latestScanId}`);
    expect(await screen.findByRole('heading', { name: 'Scan completed' })).toBeInTheDocument();
    expect(screen.getByText('7 PII findings detected')).toBeInTheDocument();
    expect(await screen.findByRole('table', { name: /Findings in employee_application.pdf/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Redact sensitive data' })).toBeInTheDocument();
  });

  it('explains a failed scan and offers a retry', async () => {
    await signInAsAdmin();
    const failed = getMockState().scans.find((scan) => scan.status === 'FAILED');
    renderApp(`/app/scans/${failed?.id}`);
    expect(await screen.findByRole('heading', { name: 'Scan failed' })).toBeInTheDocument();
    expect(screen.getByText("We couldn't complete this scan.")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('shows not found for unknown scans', async () => {
    await signInAsAdmin();
    renderApp('/app/scans/does-not-exist');
    expect(await screen.findByText('Not found')).toBeInTheDocument();
  });
});

describe('FindingsPage', () => {
  it('opens a detail drawer with a masked value', async () => {
    await signInAsAdmin();
    renderApp('/app/findings');
    const table = await screen.findByRole('table', { name: 'Findings' });
    const [firstLink] = await within(table).findAllByRole('link');
    await userEvent.click(firstLink?.closest('tr')?.querySelector('td') as HTMLElement);
    const drawer = await screen.findByRole('dialog');
    expect(within(drawer).getByText('Why this was flagged')).toBeInTheDocument();
    expect(within(drawer).getByLabelText('Masked value').textContent).toMatch(/X|•/);
    expect(within(drawer).getByRole('link', { name: 'Open in document' })).toBeInTheDocument();
  });

  it('sends anonymous visitors of admin pages to the administrator sign-in', async () => {
    const { router } = renderApp('/app/audit-logs');
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/login'));
    expect(router.state.location.search).toBe(`?next=${encodeURIComponent('/app/audit-logs')}`);
  });
});

describe('SettingsPage API keys', () => {
  it('creates a key, shows it once, and revokes it', async () => {
    const user = userEvent.setup();
    await signInAsAdmin();
    renderApp('/app/settings');
    const section = await screen.findByRole('region', { name: 'API keys' }, { timeout: 5000 });
    expect(await within(section).findByText('No API keys yet.')).toBeInTheDocument();

    await user.type(within(section).getByLabelText('Key name'), 'HR intake');
    await user.click(within(section).getByRole('button', { name: 'Create key' }));
    expect(await within(section).findByText(/won't be shown again/)).toBeInTheDocument();
    const key = getMockState().apiKeys[0];
    expect(key?.name).toBe('HR intake');
    const list = await within(section).findByRole('list', { name: 'API keys' });
    expect(within(list).getByText('HR intake')).toBeInTheDocument();

    await user.click(within(list).getByRole('button', { name: 'Revoke HR intake' }));
    await user.click(await screen.findByRole('button', { name: 'Revoke key' }));
    expect(await within(section).findByText('No API keys yet.')).toBeInTheDocument();
    expect(getMockState().apiKeys).toHaveLength(0);
  });
});
