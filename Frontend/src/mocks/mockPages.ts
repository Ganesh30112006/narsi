/**
 * Mock-only: synthetic document content, page layout and rendering.
 * Layout is shared between the SVG renderer and finding bounding boxes so highlights line up.
 */
import type { BoundingBox, PIIType } from '../types/finding';
import type { RedactionAction } from '../types/redaction';
import { maskValue } from '../utils/security';

export const PAGE_WIDTH = 816;
export const PAGE_HEIGHT = 1056;

export type MockLine =
  | { kind: 'title'; text: string }
  | { kind: 'subtitle'; text: string }
  | { kind: 'heading'; text: string }
  | { kind: 'text'; text: string }
  | { kind: 'rule' }
  | { kind: 'field'; label: string; value: string; piiType: PIIType | null; key: string };

export interface MockPageContent {
  lines: MockLine[];
}

interface PositionedLine {
  line: MockLine;
  y: number;
}

const MARGIN_X = 72;
const VALUE_X = 292;
const CHAR_WIDTH = 8.3;

function lineHeight(line: MockLine): number {
  switch (line.kind) {
    case 'title':
      return 36;
    case 'subtitle':
      return 40;
    case 'heading':
      return 44;
    case 'rule':
      return 24;
    case 'text':
      return 26;
    case 'field':
      return 38;
  }
}

export function layoutPage(page: MockPageContent): PositionedLine[] {
  let y = 96;
  return page.lines.map((line) => {
    const positioned = { line, y };
    y += lineHeight(line);
    return positioned;
  });
}

export function valueBox(y: number, value: string): BoundingBox {
  const width = value.length * CHAR_WIDTH + 12;
  return {
    x: (VALUE_X - 6) / PAGE_WIDTH,
    y: (y - 19) / PAGE_HEIGHT,
    width: width / PAGE_WIDTH,
    height: 27 / PAGE_HEIGHT,
  };
}

export function boxesForKey(pages: MockPageContent[], key: string): { page: number; box: BoundingBox } | null {
  for (let index = 0; index < pages.length; index += 1) {
    const page = pages[index];
    if (!page) continue;
    for (const { line, y } of layoutPage(page)) {
      if (line.kind === 'field' && line.key === key) {
        return { page: index + 1, box: valueBox(y, line.value) };
      }
    }
  }
  return null;
}

function escapeXml(value: string): string {
  return value.replace(/[<>&'"]/g, (char) => `&#${char.charCodeAt(0)};`);
}

/** Renders a page as SVG. Redaction actions (for sanitized copies) are applied to the content. */
export function renderPageSvg(
  page: MockPageContent,
  pageNumber: number,
  pageCount: number,
  redactions: Record<string, RedactionAction> = {},
): string {
  const parts: string[] = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${PAGE_WIDTH}" height="${PAGE_HEIGHT}" viewBox="0 0 ${PAGE_WIDTH} ${PAGE_HEIGHT}" font-family="Georgia, 'Times New Roman', serif">`,
    `<rect width="100%" height="100%" fill="#ffffff"/>`,
  ];

  for (const { line, y } of layoutPage(page)) {
    switch (line.kind) {
      case 'title':
        parts.push(
          `<text x="${MARGIN_X}" y="${y}" font-size="24" font-weight="700" fill="#1c1917">${escapeXml(line.text)}</text>`,
        );
        break;
      case 'subtitle':
        parts.push(`<text x="${MARGIN_X}" y="${y}" font-size="13" fill="#6b6560">${escapeXml(line.text)}</text>`);
        break;
      case 'heading':
        parts.push(
          `<text x="${MARGIN_X}" y="${y + 8}" font-size="16" font-weight="700" fill="#292524">${escapeXml(line.text)}</text>`,
        );
        break;
      case 'rule':
        parts.push(
          `<line x1="${MARGIN_X}" x2="${PAGE_WIDTH - MARGIN_X}" y1="${y}" y2="${y}" stroke="#d6d3d1" stroke-width="1"/>`,
        );
        break;
      case 'text':
        parts.push(`<text x="${MARGIN_X}" y="${y}" font-size="14" fill="#44403c">${escapeXml(line.text)}</text>`);
        break;
      case 'field': {
        parts.push(`<text x="${MARGIN_X}" y="${y}" font-size="13" fill="#78716c">${escapeXml(line.label)}</text>`);
        parts.push(
          `<line x1="${VALUE_X - 4}" x2="${PAGE_WIDTH - MARGIN_X}" y1="${y + 8}" y2="${y + 8}" stroke="#e7e5e4" stroke-width="1"/>`,
        );
        const action = redactions[line.key];
        if (action === 'REDACT') {
          const box = valueBox(y, line.value);
          parts.push(
            `<rect x="${box.x * PAGE_WIDTH}" y="${box.y * PAGE_HEIGHT}" width="${box.width * PAGE_WIDTH}" height="${box.height * PAGE_HEIGHT}" fill="#111111"/>`,
          );
        } else {
          const shown = action === 'MASK' && line.piiType ? maskValue(line.value, line.piiType) : line.value;
          parts.push(
            `<text x="${VALUE_X}" y="${y}" font-size="15" fill="#1c1917" font-family="'Courier New', monospace">${escapeXml(shown)}</text>`,
          );
        }
        break;
      }
    }
  }

  parts.push(
    `<text x="${PAGE_WIDTH / 2}" y="${PAGE_HEIGHT - 40}" font-size="11" fill="#a8a29e" text-anchor="middle">Page ${pageNumber} of ${pageCount} · Synthetic sample document (mock mode)</text>`,
  );
  parts.push('</svg>');
  return parts.join('');
}

/** Plain-text rendering, used for mock downloads. */
export function renderText(pages: MockPageContent[], redactions: Record<string, RedactionAction> = {}): string {
  const out: string[] = ['SYNTHETIC SAMPLE DOCUMENT — generated by GovPII Guard mock mode', ''];
  pages.forEach((page, index) => {
    out.push(`--- Page ${index + 1} ---`);
    for (const line of page.lines) {
      if (line.kind === 'rule') out.push('');
      else if (line.kind === 'field') {
        const action = redactions[line.key];
        const value =
          action === 'REDACT'
            ? '[REDACTED]'
            : action === 'MASK' && line.piiType
              ? maskValue(line.value, line.piiType)
              : line.value;
        out.push(`${line.label}: ${value}`);
      } else out.push(line.text);
    }
    out.push('');
  });
  return out.join('\n');
}

/** Minimal single-font PDF writer for mock report exports. */
export function renderSimplePdf(title: string, lines: string[]): Blob {
  const escapePdf = (text: string) => text.replace(/[\\()]/g, (char) => `\\${char}`).replace(/[^\x20-\x7e]/g, '-');
  const content = [
    'BT',
    '/F1 18 Tf',
    '72 760 Td',
    `(${escapePdf(title)}) Tj`,
    '/F1 11 Tf',
    '0 -28 Td',
    ...lines.flatMap((line) => [`(${escapePdf(line)}) Tj`, '0 -16 Td']),
    'ET',
  ].join('\n');

  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];

  let pdf = '%PDF-1.4\n';
  const offsets: number[] = [];
  objects.forEach((object, index) => {
    offsets.push(pdf.length);
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  return new Blob([pdf], { type: 'application/pdf' });
}
