import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { buildContent } from '../mocks/mockDb';
import { getMockState } from '../mocks/mockTransport';
import { renderApp } from './utils';

const PDF_BYTES = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x37, 0x0a]);
const JPG_BYTES = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00]);

describe('End-to-end user journey (mock backend)', () => {
  it('admin: login → upload → scan → inspect → redact → report → audit → logout', async () => {
    const user = userEvent.setup();
    const { router } = renderApp('/admin/login');

    // Login
    await user.type(await screen.findByLabelText('Username'), 'admin');
    await user.type(screen.getByLabelText('Password'), 'GuardDemo#2026');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { level: 1, name: /Ananya/ }, { timeout: 5000 })).toBeInTheDocument();

    // Upload (validated locally, then uploaded and scanned)
    await act(() => router.navigate('/app/documents/upload'));
    const file = new File([PDF_BYTES], 'vendor_contract.pdf', { type: 'application/pdf' });
    fireEvent.change(await screen.findByTestId('file-input'), { target: { files: [file] } });
    expect(await screen.findByText('Ready to upload')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Upload' }));
    const viewScan = await screen.findByRole('link', { name: 'View scan' });
    expect(screen.getByText('Uploaded · scan started')).toBeInTheDocument();

    // Give the uploaded document known content, then let the simulated scan finish.
    const state = getMockState();
    const uploaded = state.documents.find((doc) => doc.fileName === 'vendor_contract.pdf');
    if (!uploaded) throw new Error('upload missing');
    uploaded.content = buildContent(uploaded.fileName, [['NAME', 'PAN'], ['AADHAAR']]);
    uploaded.pageCount = 2;

    await user.click(viewScan);
    expect(await screen.findByRole('heading', { name: 'Scanning document' })).toBeInTheDocument();
    const scan = state.scans.find((candidate) => candidate.documentId === uploaded.id);
    if (!scan) throw new Error('scan missing');
    scan.startedAtMs -= 120_000;

    expect(await screen.findByRole('heading', { name: 'Scan completed' }, { timeout: 6000 })).toBeInTheDocument();
    expect(screen.getByText('3 PII findings detected')).toBeInTheDocument();
    expect(await screen.findByRole('table', { name: /Findings in vendor_contract.pdf/ })).toBeInTheDocument();

    // Open the document and highlight a finding
    await user.click(screen.getByRole('link', { name: 'Open document' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'vendor_contract.pdf' })).toBeInTheDocument();
    const highlight = await screen.findByRole('button', { name: /^PAN, \d+% confidence/ });
    await user.click(highlight);
    expect(highlight).toHaveAttribute('aria-pressed', 'true');
    const popover = await screen.findByRole('dialog', { name: 'PAN explanation' });
    expect(within(popover).getByText('Why this was flagged')).toBeInTheDocument();

    // Redact → sanitized copy → download
    await user.click(screen.getByRole('button', { name: 'Redact sensitive data' }));
    const redactDialog = await screen.findByRole('dialog', { name: 'Redact sensitive data' });
    expect(within(redactDialog).getByText('3 to redact · 0 to mask · 0 preserved')).toBeInTheDocument();
    await user.click(within(redactDialog).getByRole('button', { name: 'Continue' }));
    expect(
      await screen.findByText('This creates a sanitized copy. The original document will remain unchanged.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create sanitized copy' }));
    const done = await screen.findByRole('dialog', { name: 'Redaction completed' });
    expect(within(done).getByText('3 findings removed')).toBeInTheDocument();
    expect(within(done).getByText('Original document')).toBeInTheDocument();
    expect(within(done).getByText('Unchanged')).toBeInTheDocument();
    expect(within(done).getByText('vendor_contract.sanitized.pdf')).toBeInTheDocument();

    const createUrl = vi.spyOn(URL, 'createObjectURL');
    await user.click(within(done).getByRole('button', { name: 'Download sanitized copy' }));
    await waitFor(() => expect(createUrl).toHaveBeenCalledWith(expect.any(Blob)));
    await user.click(within(done).getByRole('button', { name: 'Close dialog' }));

    // Report
    await act(() => router.navigate(`/app/reports/${scan.reportId}`));
    const report = await screen.findByRole('article', { name: 'vendor_contract.pdf' });
    expect(within(report).getByText('Redacted')).toBeInTheDocument();
    await user.click(within(report).getByRole('button', { name: 'Export JSON' }));
    expect(await screen.findByText('Report generated')).toBeInTheDocument();

    // Audit trail (no sensitive values)
    await act(() => router.navigate('/app/audit-logs'));
    const auditTable = await screen.findByRole('table', { name: 'Audit log' });
    await within(auditTable).findAllByText('Created redacted copy');
    expect(within(auditTable).getAllByText('Downloaded report').length).toBeGreaterThan(0);
    expect(within(auditTable).getAllByText('Uploaded document').length).toBeGreaterThan(0);
    const rawValues = state.findings.filter((finding) => finding.documentId === uploaded.id).map((finding) => finding.rawValue);
    for (const raw of rawValues) expect(document.body.textContent).not.toContain(raw);

    // Logout
    await user.click(screen.getByRole('button', { name: /Account menu/ }));
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }));
    expect(await screen.findByRole('heading', { name: 'Administrator sign in' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/admin/login');
  }, 30_000);
});

describe('Public journey (no sign-in, mock backend)', () => {
  it('uploads several files at once and links to each result', async () => {
    const { router } = renderApp('/');
    const files = ['a.pdf', 'b.pdf'].map((name) => new File([PDF_BYTES], name, { type: 'application/pdf' }));
    fireEvent.change(await screen.findByTestId('file-input'), { target: { files } });
    const list = await screen.findByRole('list', { name: 'Uploaded files' }, { timeout: 5000 });
    expect(within(list).getAllByRole('link', { name: 'View results' })).toHaveLength(2);
    expect(router.state.location.pathname).toBe('/');
    expect(screen.getByText(/every time they do it is logged/)).toBeInTheDocument();
  });

  it('refuses more than five files in one go', async () => {
    renderApp('/');
    const files = Array.from({ length: 6 }, (_, i) => new File([PDF_BYTES], `${i}.pdf`, { type: 'application/pdf' }));
    fireEvent.change(await screen.findByTestId('file-input'), { target: { files } });
    expect(await screen.findByText('Choose up to 5 files at a time.')).toBeInTheDocument();
  });

  it('upload → results → redacted copy → report → delete', async () => {
    const user = userEvent.setup();
    const { router } = renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Check a document for personal data' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Administrator sign in' })).toBeInTheDocument();

    const file = new File([PDF_BYTES], 'my_application.pdf', { type: 'application/pdf' });
    fireEvent.change(await screen.findByTestId('file-input'), { target: { files: [file] } });
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/results\//));

    // Known content, then let the simulated scan finish.
    const state = getMockState();
    const uploaded = state.documents.find((doc) => doc.fileName === 'my_application.pdf');
    const scan = state.scans.find((candidate) => candidate.documentId === uploaded?.id);
    if (!uploaded || !scan) throw new Error('upload missing');
    expect(uploaded.uploadedBy.name).toBe('Public upload');
    uploaded.content = buildContent(uploaded.fileName, [['NAME', 'PAN'], ['AADHAAR']]);
    uploaded.pageCount = 2;
    scan.startedAtMs -= 120_000;

    expect(await screen.findByRole('heading', { name: '3 items of personal data found' }, { timeout: 6000 })).toBeInTheDocument();
    // Is the ID number valid? Answered per number, with what the answer does and doesn't prove.
    const idCheck = screen.getByRole('region', { name: 'Are these ID numbers valid?' });
    expect(within(idCheck).getByRole('link', { name: /myaadhaar.uidai.gov.in/ })).toHaveAttribute(
      'href',
      'https://myaadhaar.uidai.gov.in/',
    );
    expect(within(idCheck).getByText(/doesn't prove the document is genuine/)).toBeInTheDocument();
    const table = await screen.findByRole('table', { name: /Personal data found in my_application.pdf/ });
    const raw = state.findings.filter((finding) => finding.documentId === uploaded.id).map((finding) => finding.rawValue);
    for (const value of raw) expect(document.body.textContent).not.toContain(value);

    // Why was it flagged?
    await user.click(within(table).getAllByRole('row')[1]?.querySelector('td') as HTMLElement);
    const drawer = await screen.findByRole('dialog', { name: 'Why this was flagged' });
    expect(within(drawer).queryByRole('button', { name: 'Reveal' })).not.toBeInTheDocument();
    await user.click(within(drawer).getByRole('button', { name: 'Close panel' }));

    // Redacted copy and report downloads
    const createUrl = vi.spyOn(URL, 'createObjectURL');
    await user.click(screen.getByRole('button', { name: 'Create redacted copy' }));
    await user.click(await screen.findByRole('button', { name: 'Download redacted copy' }, { timeout: 6000 }));
    await waitFor(() => expect(createUrl).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: 'PDF' }));
    await waitFor(() => expect(createUrl).toHaveBeenCalledTimes(2));

    // Delete now
    await user.click(screen.getByRole('button', { name: 'Delete my file now' }));
    await user.click(
      within(await screen.findByRole('alertdialog', { name: 'Delete your file now?' })).getByRole('button', { name: 'Delete' }),
    );
    await waitFor(() => expect(router.state.location.pathname).toBe('/'));
    expect(getMockState().documents.some((doc) => doc.fileName.startsWith('my_application'))).toBe(false);
  }, 30_000);

  it("doesn't call an unreadable photo clean", async () => {
    const { router } = renderApp('/');
    const file = new File([JPG_BYTES], 'blurry_aadhaar_photo.jpg', { type: 'image/jpeg' });
    fireEvent.change(await screen.findByTestId('file-input'), { target: { files: [file] } });
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/results\//));
    const state = getMockState();
    const uploaded = state.documents.find((doc) => doc.fileName === 'blurry_aadhaar_photo.jpg');
    const scan = state.scans.find((candidate) => candidate.documentId === uploaded?.id);
    if (!scan) throw new Error('upload missing');
    scan.startedAtMs -= 120_000;

    expect(
      await screen.findByRole('heading', { name: "We couldn't read this file clearly" }, { timeout: 6000 }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Don't treat this file as safe to share/)).toBeInTheDocument();
    expect(screen.queryByText('No personal data found')).not.toBeInTheDocument();
    expect(screen.queryByText('Nothing found')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Check another file' })).toHaveAttribute('href', '/');
  }, 30_000);

  it("doesn't open results without this tab's access token", async () => {
    renderApp('/results/scn_anything');
    expect(await screen.findByText("These results aren't available here")).toBeInTheDocument();
  });
});
