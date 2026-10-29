import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { RequireAuth } from '../app/routeGuards';
import { renderWithProviders, signInAsAdmin } from '../test/utils';
import type { Finding } from '../types/finding';
import { FileDropzone } from './documents/FileDropzone';
import { ConfidenceIndicator } from './findings/ConfidenceIndicator';
import { FindingExplanation } from './findings/FindingExplanation';
import { Button } from './ui/Button';
import { ConfirmDialog } from './ui/Dialog';
import { ConfidenceBadge, ScanStatusBadge, ValidationBadge } from './ui/StatusBadge';

const finding: Finding = {
  id: 'fnd_1',
  scanId: 'scn_1',
  documentId: 'doc_1',
  documentName: 'employee_application.pdf',
  piiType: 'PAN',
  maskedValue: 'XXXXXX234F',
  confidence: 0.96,
  confidenceLevel: 'HIGH',
  detectionMethod: 'HYBRID',
  detectionSignals: ['PATTERN', 'CONTEXT', 'CHECKSUM'],
  validationStatus: 'VALIDATED',
  location: { page: 2, boxes: [], sheet: null, cell: null, line: null },
  reasons: [
    { code: 'FORMAT', label: 'Format matched', passed: true },
    { code: 'CONTEXT', label: 'Nearby PAN label', passed: false },
  ],
  contextSnippet: 'PAN No: XXXXXX234F',
  redactionState: 'NONE',
  createdAt: '2026-09-30T10:00:00Z',
};

describe('Button', () => {
  it('fires clicks and is disabled while loading', async () => {
    const onClick = vi.fn();
    const { rerender } = render(<Button onClick={onClick}>Save</Button>);
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(
      <Button onClick={onClick} loading loadingLabel="Saving">
        Save
      </Button>,
    );
    const button = screen.getByRole('button', { name: /save/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
  });
});

describe('Status badges', () => {
  it('always pair colour with a text label', () => {
    render(
      <>
        <ConfidenceBadge level="HIGH" />
        <ConfidenceBadge level="MEDIUM" />
        <ValidationBadge status="VALIDATED" />
        <ScanStatusBadge status="PROCESSING" />
        <ScanStatusBadge status="FAILED" />
      </>,
    );
    for (const text of ['High confidence', 'Medium confidence', 'Validated', 'Processing', 'Failed']) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
  });

  it('describes confidence in text for screen readers', () => {
    render(<ConfidenceIndicator confidence={0.82} level="MEDIUM" />);
    expect(screen.getByText('82%')).toBeInTheDocument();
    expect(screen.getByText('Medium confidence')).toBeInTheDocument();
  });
});

describe('ConfirmDialog', () => {
  it('focuses the safe action, confirms and closes on Escape', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Delete this document?"
        confirmLabel="Delete"
        tone="danger"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    const dialog = screen.getByRole('alertdialog', { name: 'Delete this document?' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});

describe('FileDropzone', () => {
  it('passes chosen and dropped files to the caller', () => {
    const onFiles = vi.fn();
    render(<FileDropzone onFiles={onFiles} />);
    const file = new File(['%PDF'], 'a.pdf', { type: 'application/pdf' });

    fireEvent.change(screen.getByTestId('file-input'), { target: { files: [file] } });
    expect(onFiles).toHaveBeenLastCalledWith([file]);

    fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [file] } });
    expect(onFiles).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Choose files' })).toBeInTheDocument();
  });
});

describe('FindingExplanation', () => {
  it('explains the detection without exposing the raw value', async () => {
    await signInAsAdmin();
    renderWithProviders(<FindingExplanation finding={finding} />);
    expect(await screen.findByText('Why this was flagged')).toBeInTheDocument();
    expect(screen.getByText('XXXXXX234F')).toBeInTheDocument();
    expect(screen.getByText('Pattern + Context + Checksum')).toBeInTheDocument();
    expect(screen.getByText('Page 2')).toBeInTheDocument();
    expect(screen.getByText('Passed:', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Not met:', { exact: false })).toBeInTheDocument();
  });

  it('offers the audited reveal to administrators only — never on public pages', async () => {
    const { unmount } = renderWithProviders(<FindingExplanation finding={finding} />);
    await screen.findByText('Why this was flagged');
    expect(screen.queryByRole('button', { name: 'Reveal' })).not.toBeInTheDocument();
    unmount();

    await signInAsAdmin();
    renderWithProviders(
      <RequireAuth>
        <FindingExplanation finding={finding} />
      </RequireAuth>,
    );
    await waitFor(() => expect(screen.getByRole('button', { name: 'Reveal' })).toBeInTheDocument());
  });

  it('never offers a reveal for a photo, QR code or signature (there is no text value)', async () => {
    await signInAsAdmin();
    const photo = {
      ...finding,
      id: 'fnd-photo',
      piiType: 'PHOTO' as const,
      maskedValue: '[photo]',
      detectionMethod: 'IMAGE' as const,
      detectionSignals: ['IMAGE' as const],
      validationStatus: 'NOT_APPLICABLE' as const,
      reasons: [{ code: 'VISUAL_FACE', label: 'A face photo (two face detectors agree)', passed: true }],
      contextSnippet: null,
    };
    renderWithProviders(
      <RequireAuth>
        <FindingExplanation finding={photo} />
      </RequireAuth>,
    );
    expect(await screen.findByText('A face photo (two face detectors agree)')).toBeInTheDocument();
    expect(screen.getByText('[photo]')).toBeInTheDocument();
    expect(screen.getByText('Image analysis')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reveal' })).not.toBeInTheDocument();
  });
});
