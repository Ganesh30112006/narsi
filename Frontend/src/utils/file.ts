import type { DocumentFileType } from '../types/document';
import { formatBytes } from './formatting';

export const MAX_UPLOAD_BYTES = (Number(import.meta.env.VITE_MAX_UPLOAD_MB ?? 50) || 50) * 1024 * 1024;

interface FileTypeRule {
  type: DocumentFileType;
  extensions: string[];
  mimeTypes: string[];
  /** How the content is verified — never trust the extension alone. */
  signature: 'pdf' | 'zip' | 'png' | 'jpg' | 'tiff' | 'text' | 'json' | 'xml';
}

export const FILE_TYPE_RULES: FileTypeRule[] = [
  { type: 'PDF', extensions: ['pdf'], mimeTypes: ['application/pdf'], signature: 'pdf' },
  {
    type: 'DOCX',
    extensions: ['docx'],
    mimeTypes: ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
    signature: 'zip',
  },
  {
    type: 'XLSX',
    extensions: ['xlsx'],
    mimeTypes: ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'],
    signature: 'zip',
  },
  {
    type: 'CSV',
    extensions: ['csv'],
    mimeTypes: ['text/csv', 'application/csv', 'text/plain', 'application/vnd.ms-excel'],
    signature: 'text',
  },
  { type: 'TXT', extensions: ['txt'], mimeTypes: ['text/plain'], signature: 'text' },
  { type: 'JSON', extensions: ['json'], mimeTypes: ['application/json', 'text/json', 'text/plain'], signature: 'json' },
  { type: 'XML', extensions: ['xml'], mimeTypes: ['application/xml', 'text/xml'], signature: 'xml' },
  { type: 'PNG', extensions: ['png'], mimeTypes: ['image/png'], signature: 'png' },
  { type: 'JPG', extensions: ['jpg', 'jpeg'], mimeTypes: ['image/jpeg'], signature: 'jpg' },
  { type: 'TIFF', extensions: ['tif', 'tiff'], mimeTypes: ['image/tiff'], signature: 'tiff' },
];

export const ACCEPT_ATTRIBUTE = FILE_TYPE_RULES.flatMap((rule) => [
  ...rule.extensions.map((extension) => `.${extension}`),
  ...rule.mimeTypes.filter((mime) => mime !== 'text/plain'),
]).join(',');

export const SUPPORTED_FORMATS_LABEL = FILE_TYPE_RULES.map((rule) => rule.type).join(', ');

export function getExtension(fileName: string): string {
  const index = fileName.lastIndexOf('.');
  return index > 0 ? fileName.slice(index + 1).toLowerCase() : '';
}

export function ruleForFileName(fileName: string): FileTypeRule | undefined {
  const extension = getExtension(fileName);
  return FILE_TYPE_RULES.find((rule) => rule.extensions.includes(extension));
}

async function readHead(file: Blob, length: number): Promise<Uint8Array> {
  const slice = file.slice(0, length);
  if (typeof slice.arrayBuffer === 'function') {
    return new Uint8Array(await slice.arrayBuffer());
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error ?? new Error('Unable to read file'));
    reader.readAsArrayBuffer(slice);
  });
}

function startsWith(bytes: Uint8Array, signature: number[]): boolean {
  return signature.every((byte, index) => bytes[index] === byte);
}

function firstNonWhitespace(bytes: Uint8Array): number | undefined {
  let index = 0;
  // Skip UTF-8 BOM
  if (startsWith(bytes, [0xef, 0xbb, 0xbf])) index = 3;
  while (index < bytes.length) {
    const byte = bytes[index];
    if (byte !== 0x20 && byte !== 0x09 && byte !== 0x0a && byte !== 0x0d) return byte;
    index += 1;
  }
  return undefined;
}

function looksLikeText(bytes: Uint8Array): boolean {
  // Binary content almost always contains NUL bytes early on.
  return !bytes.includes(0);
}

export function matchesSignature(bytes: Uint8Array, signature: FileTypeRule['signature']): boolean {
  switch (signature) {
    case 'pdf':
      return startsWith(bytes, [0x25, 0x50, 0x44, 0x46]); // %PDF
    case 'zip':
      return startsWith(bytes, [0x50, 0x4b, 0x03, 0x04]); // PK..
    case 'png':
      return startsWith(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    case 'jpg':
      return startsWith(bytes, [0xff, 0xd8, 0xff]);
    case 'tiff':
      return startsWith(bytes, [0x49, 0x49, 0x2a, 0x00]) || startsWith(bytes, [0x4d, 0x4d, 0x00, 0x2a]);
    case 'text':
      return looksLikeText(bytes);
    case 'json': {
      const first = firstNonWhitespace(bytes);
      return looksLikeText(bytes) && (first === 0x7b || first === 0x5b); // { or [
    }
    case 'xml':
      return looksLikeText(bytes) && firstNonWhitespace(bytes) === 0x3c; // <
  }
}

export type FileValidationResult = { ok: true; fileType: DocumentFileType } | { ok: false; reason: string };

export async function validateFile(file: File, maxBytes: number = MAX_UPLOAD_BYTES): Promise<FileValidationResult> {
  const rule = ruleForFileName(file.name);
  if (!rule) {
    return { ok: false, reason: `This file type isn't supported. Supported formats: ${SUPPORTED_FORMATS_LABEL}.` };
  }
  if (file.size === 0) {
    return { ok: false, reason: 'This file is empty.' };
  }
  if (file.size > maxBytes) {
    return { ok: false, reason: `This file is too large. Maximum file size: ${formatBytes(maxBytes)}.` };
  }
  if (file.type && !rule.mimeTypes.includes(file.type) && file.type !== 'application/octet-stream') {
    return { ok: false, reason: `The file's content type doesn't match a ${rule.type} file.` };
  }

  let head: Uint8Array;
  try {
    head = await readHead(file, 4096);
  } catch {
    return { ok: false, reason: "This file couldn't be read. It may be open in another program." };
  }
  if (!matchesSignature(head, rule.signature)) {
    return { ok: false, reason: `This file doesn't look like a valid ${rule.type} file.` };
  }
  return { ok: true, fileType: rule.type };
}

/** Triggers a browser download for a Blob without leaving the page. */
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  anchor.rel = 'noopener';
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
