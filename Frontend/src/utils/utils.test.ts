import { describe, expect, it } from 'vitest';
import { matchesSignature, validateFile } from './file';
import { formatBytes, formatPercent, initials } from './formatting';
import { hasPermission, maskValue, safeRedirectPath, sanitizeFileName } from './security';
import { degradedSummary } from './health';
import { validateLoginForm, validateNewPassword, validateUsername } from './validation';
import type { PublicFinding } from '../types/public';
import {
  describeWhere,
  groupFindings,
  idVerdict,
  isIdType,
  isVisualType,
  unreadablePageText,
  valueChecks,
  verdictText,
  verificationText,
} from './publicResults';

const PDF_BYTES = [0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34];
const PNG_BYTES = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

function fileOf(bytes: number[] | string, name: string, type = '') {
  const content = typeof bytes === 'string' ? bytes : new Uint8Array(bytes);
  return new File([content], name, { type });
}

describe('validateFile', () => {
  it('accepts a PDF whose content matches its extension', async () => {
    await expect(validateFile(fileOf(PDF_BYTES, 'form.pdf', 'application/pdf'))).resolves.toEqual({ ok: true, fileType: 'PDF' });
  });

  it('rejects unsupported extensions', async () => {
    const result = await validateFile(fileOf('MZ', 'setup.exe'));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/isn't supported/);
  });

  it('rejects empty files', async () => {
    const result = await validateFile(fileOf([], 'empty.pdf'));
    expect(result).toEqual({ ok: false, reason: 'This file is empty.' });
  });

  it('rejects files over the size limit', async () => {
    const result = await validateFile(fileOf(PDF_BYTES, 'big.pdf'), 4);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/Maximum file size/);
  });

  it('does not trust the extension alone', async () => {
    const result = await validateFile(fileOf(PNG_BYTES, 'renamed.pdf'));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/doesn't look like a valid PDF/);
  });

  it('rejects a mismatched MIME type', async () => {
    const result = await validateFile(fileOf(PDF_BYTES, 'form.pdf', 'image/png'));
    expect(result.ok).toBe(false);
  });

  it('validates structured text formats', () => {
    const encode = (text: string) => new TextEncoder().encode(text);
    expect(matchesSignature(encode('  {"a":1}'), 'json')).toBe(true);
    expect(matchesSignature(encode('name,pan'), 'json')).toBe(false);
    expect(matchesSignature(encode('<?xml version="1.0"?>'), 'xml')).toBe(true);
    expect(matchesSignature(new Uint8Array([0x61, 0x00, 0x62]), 'text')).toBe(false);
  });
});

describe('masking and security helpers', () => {
  it('masks government identifiers leaving only a short suffix', () => {
    expect(maskValue('ABCPD1234F', 'PAN')).toBe('XXXXXX234F');
    expect(maskValue('4821 7730 5519', 'AADHAAR')).toBe('XXXXXXXX5519');
    expect(maskValue('r.kumar@example.in', 'EMAIL')).toBe('r••••••@example.in');
  });

  it('only allows in-app redirects', () => {
    expect(safeRedirectPath('/app/findings?x=1')).toBe('/app/findings?x=1');
    expect(safeRedirectPath('https://evil.example')).toBe('/app/dashboard');
    expect(safeRedirectPath('//evil.example/app')).toBe('/app/dashboard');
    expect(safeRedirectPath('/login')).toBe('/app/dashboard');
    expect(safeRedirectPath('/admin/login')).toBe('/app/dashboard');
    expect(safeRedirectPath(null)).toBe('/app/dashboard');
  });

  it('sanitizes server-provided file names', () => {
    expect(sanitizeFileName('../../etc/passwd')).toBe('_.._etc_passwd');
    expect(sanitizeFileName('')).toBe('download');
  });

  it('maps roles to permissions', () => {
    expect(hasPermission('admin', 'pii:reveal')).toBe(true);
    expect(hasPermission(null, 'documents:read')).toBe(false);
  });
});

describe('validation', () => {
  it('validates login input', () => {
    expect(validateLoginForm('', '')).toEqual({ username: 'Enter your username.', password: 'Enter your password.' });
    expect(validateLoginForm('x'.repeat(65), 'x').username).toBe('Usernames are at most 64 characters.');
    expect(validateLoginForm(' admin ', 'secret')).toEqual({});
    expect(validateUsername('admin')).toBeNull();
  });

  it('enforces password rules', () => {
    expect(validateNewPassword('short')).toMatch(/12 characters/);
    expect(validateNewPassword('Longenough123!')).toBeNull();
  });
});

describe('formatting', () => {
  it('formats sizes, percentages and initials', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
    expect(formatPercent(0.96)).toBe('96%');
    expect(formatPercent(null)).toBe('—');
    expect(initials('Ananya Rao')).toBe('AR');
  });
});

function publicFinding(overrides: Partial<PublicFinding>): PublicFinding {
  return {
    id: 'f1',
    scanId: 's1',
    documentId: 'd1',
    documentName: 'letter.pdf',
    piiType: 'AADHAAR',
    maskedValue: 'XXXXXXXX5885',
    confidence: 0.7,
    confidenceLevel: 'MEDIUM',
    detectionMethod: 'HYBRID',
    detectionSignals: ['PATTERN', 'CHECKSUM'],
    validationStatus: 'VALIDATED',
    location: { page: 1, boxes: [], sheet: null, cell: null, line: null },
    reasons: [
      { code: 'FORMAT', label: 'Matches the expected 12-digit Aadhaar number structure', passed: true },
      { code: 'AADHAAR_CHECKSUM', label: 'Verhoeff check digit matches the Aadhaar structure', passed: true },
      { code: 'OCR', label: 'Read from an image by OCR', passed: true },
    ],
    contextSnippet: null,
    redactionState: 'NONE',
    createdAt: '2026-10-01T00:00:00Z',
    group: 'g-aadhaar',
    ...overrides,
  };
}

describe('public results', () => {
  const findings = [
    publicFinding({ id: 'a1', confidence: 0.72 }),
    publicFinding({
      id: 'n1',
      piiType: 'NAME',
      maskedValue: 'R••• K••••',
      group: 'g-name',
      confidence: 0.6,
      validationStatus: 'NOT_APPLICABLE',
      reasons: [],
    }),
    publicFinding({ id: 'a2', confidence: 0.91, location: { page: 2, boxes: [], sheet: null, cell: null, line: null } }),
    publicFinding({ id: 'a3', confidence: 0.72 }),
    publicFinding({
      id: 'v1',
      piiType: 'AADHAAR_VID',
      maskedValue: 'XXXXXXXXXXXX7816',
      group: 'g-vid',
      validationStatus: 'FAILED_VALIDATION',
    }),
  ];

  it('collapses repeated values into one item, IDs first', () => {
    const items = groupFindings(findings);
    expect(items.map((item) => item.piiType)).toEqual(['AADHAAR', 'AADHAAR_VID', 'NAME']);
    const [aadhaar] = items;
    expect(aadhaar?.occurrences).toHaveLength(3);
    expect(aadhaar?.best.id).toBe('a2');
    expect(aadhaar && describeWhere(aadhaar)).toBe('Pages 1 and 2 · 3 times');
    expect(describeWhere(items[2]!)).toBe('Page 1');
  });

  it('turns the structural check into a plain verdict, with only the checks on the value', () => {
    const [aadhaar, vid, name] = groupFindings(findings);
    expect(idVerdict(aadhaar!)).toBe('valid');
    expect(verdictText(aadhaar!).title).toBe('Valid number');
    expect(verdictText(aadhaar!).detail).toMatch(/Verhoeff/);
    expect(valueChecks(aadhaar!.best).map((reason) => reason.code)).toEqual(['AADHAAR_CHECKSUM']);
    expect(idVerdict(vid!)).toBe('invalid');
    expect(verdictText(vid!).title).toBe('Not a valid number');
    expect(isIdType(name!.piiType)).toBe(false);
    expect(verdictText(groupFindings([publicFinding({ piiType: 'PAN', group: 'p' })])[0]!).title).toBe('Valid format');
  });
});

describe('passport verdict', () => {
  it('uses the MRZ check digit when one was checked', () => {
    const checked = publicFinding({
      piiType: 'PASSPORT',
      maskedValue: 'XXXXX431',
      group: 'p',
      reasons: [{ code: 'PASSPORT_MRZ_CHECK', label: 'Machine-readable zone check digit matches the number', passed: true }],
    });
    expect(verdictText(groupFindings([checked])[0]!).title).toBe('Valid number');
    expect(verdictText(groupFindings([checked])[0]!).detail).toMatch(/ICAO 9303/);
    const shapeOnly = publicFinding({ piiType: 'PASSPORT', maskedValue: 'XXXXX431', group: 'q', reasons: [] });
    expect(verdictText(groupFindings([shapeOnly])[0]!).title).toBe('Valid format');
  });
});

describe('photos, QR codes and signatures', () => {
  const qr = publicFinding({
    id: 'q1',
    piiType: 'QR_CODE',
    maskedValue: '[QR code]',
    group: 'g-qr',
    confidence: 0.88,
    detectionMethod: 'IMAGE',
    detectionSignals: ['IMAGE'],
    validationStatus: 'NOT_APPLICABLE',
    reasons: [{ code: 'VISUAL_QR', label: 'A dense square module pattern, as in a QR code', passed: true }],
  });

  it('are listed after ID numbers and have no ID check', () => {
    const items = groupFindings([qr, publicFinding({ id: 'a1' })]);
    expect(items.map((item) => item.piiType)).toEqual(['AADHAAR', 'QR_CODE']);
    expect(isVisualType('QR_CODE') && isVisualType('PHOTO') && isVisualType('SIGNATURE')).toBe(true);
    expect(isVisualType('AADHAAR') || isIdType('QR_CODE')).toBe(false);
    expect(describeWhere(items[1]!)).toBe('Page 1');
  });

  it('are masked by kind, never by characters', () => {
    expect(maskValue('PHOTO@1:0.1,0.1,0.2,0.2', 'PHOTO')).toBe('[photo]');
    expect(maskValue('anything', 'QR_CODE')).toBe('[QR code]');
    expect(maskValue('anything', 'SIGNATURE')).toBe('[signature]');
  });

  it('say how the redacted copy was checked', () => {
    expect(verificationText('text-extraction')).toBe(
      'Checked: the copy was re-read and none of the removed values can be recovered.',
    );
    expect(verificationText('ocr')).toMatch(/re-read with OCR/);
    const both = verificationText('ocr+pixels');
    expect(both).toMatch(/re-read with OCR/);
    expect(both).toMatch(/Photos, QR codes and signatures were confirmed to be solid black/);
    expect(verificationText(undefined)).not.toMatch(/OCR|solid black/);
  });
});

describe('unreadablePageText', () => {
  it('names the file, one page or several', () => {
    expect(unreadablePageText([1], 1)).toBe('The file is');
    expect(unreadablePageText([2], 4)).toBe('Page 2 is');
    expect(unreadablePageText([1, 2, 4], 5)).toBe('Pages 1, 2 and 4 are');
  });
});

describe('degradedSummary', () => {
  it('names each part that is not healthy, with its reason', () => {
    expect(
      degradedSummary([
        { name: 'database', status: 'healthy', critical: true },
        { name: 'deep_ocr', status: 'degraded', critical: false, detail: 'PP-OCR not installed' },
        { name: 'gpu', status: 'degraded', critical: false },
      ]),
    ).toEqual(['Photo text recognition: PP-OCR not installed', 'GPU acceleration']);
    expect(degradedSummary(undefined)).toEqual([]);
  });
});
