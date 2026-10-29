import { VISUAL_TYPES, type DetectionReason, type PIIType } from '../types/finding';
import type { DocumentTypeGuess, PublicFinding, SignatureStatus } from '../types/public';
import { pluralize } from './formatting';

/** Government-issued identifiers — the values a structural check can say something about. */
export const ID_TYPES: readonly PIIType[] = ['AADHAAR', 'AADHAAR_VID', 'PAN', 'PASSPORT', 'VOTER_ID', 'DRIVING_LICENSE'];

/** Identifiers whose last digit is a check digit, so a mistyped or invented number almost always fails. */
const CHECKSUM_TYPES: ReadonlySet<PIIType> = new Set(['AADHAAR', 'AADHAAR_VID']);

/** Reason codes that describe how a value was found, rather than a check of the value itself. */
const DETECTION_CODES: ReadonlySet<string> = new Set(['FORMAT', 'CONTEXT', 'NEGATIVE_CONTEXT', 'NER', 'OCR', 'REPEATED']);

const ID_NOUNS: Partial<Record<PIIType, string>> = {
  AADHAAR: 'Aadhaar number',
  AADHAAR_VID: 'Aadhaar Virtual ID (VID)',
  PAN: 'PAN',
  PASSPORT: 'passport number',
  VOTER_ID: 'voter ID (EPIC) number',
  DRIVING_LICENSE: 'driving licence number',
};

/** One distinct value found in the file, with every place it appears. */
export interface ResultItem {
  key: string;
  piiType: PIIType;
  maskedValue: string;
  /** The occurrence detected with the most confidence. Its explanation stands for the whole item. */
  best: PublicFinding;
  occurrences: PublicFinding[];
  pages: number[];
}

export type IdVerdict = 'valid' | 'invalid' | 'unchecked';

export interface OfficialCheck {
  text: string;
  href: string;
  site: string;
}

const AADHAAR_CHECK: OfficialCheck = {
  text: 'To confirm UIDAI really issued it, use the Verify Aadhaar service, or scan the secure QR code on the letter with the mAadhaar app.',
  href: 'https://myaadhaar.uidai.gov.in/',
  site: 'myaadhaar.uidai.gov.in',
};

/** Where a person can confirm that an identifier was actually issued. Only the issuer can say that. */
export const OFFICIAL_CHECKS: Partial<Record<PIIType, OfficialCheck>> = {
  AADHAAR: AADHAAR_CHECK,
  AADHAAR_VID: AADHAAR_CHECK,
  PAN: {
    text: 'To confirm the PAN was really issued, use “Verify your PAN” on the Income Tax e-filing portal.',
    href: 'https://www.incometax.gov.in/',
    site: 'incometax.gov.in',
  },
};

export function isIdType(type: PIIType): boolean {
  return ID_TYPES.includes(type);
}

const SIGNATURE_TITLES: Record<SignatureStatus, string> = {
  VALID: 'Digitally signed, unchanged',
  ALTERED: 'Changed after signing',
  UNTRUSTED: 'Signed, but not by a recognised Indian authority',
  INVALID: 'Signature does not match the document',
};

export function signatureTitle(status: SignatureStatus): string {
  return SIGNATURE_TITLES[status];
}

const DOCUMENT_TYPE_NAMES: Record<DocumentTypeGuess['label'], string> = {
  AADHAAR: 'an Aadhaar document',
  PAN: 'a PAN card',
  PASSPORT: 'a passport',
  VOTER_ID: 'a voter ID (EPIC) card',
  DRIVING_LICENSE: 'a driving licence',
  CERTIFICATE: 'a school or board certificate',
  OTHER: 'a general document',
  UNKNOWN: 'an unrecognised document',
};

/** "Looks like a passport (97% sure)", or nothing when the guess is too weak to show. */
export function documentTypeText(guess: DocumentTypeGuess | null | undefined): string | null {
  if (!guess || guess.label === 'UNKNOWN') return null;
  return `Looks like ${DOCUMENT_TYPE_NAMES[guess.label]} (${Math.round(guess.probability * 100)}% sure)`;
}

export function isVisualType(type: PIIType): boolean {
  return VISUAL_TYPES.includes(type);
}

/** What the server checked before handing out the redacted copy (the verification method it reports). */
export function verificationText(method: string | undefined): string {
  const ocr = method?.startsWith('ocr') ?? false;
  const pixels = method?.includes('+pixels') ?? false;
  return (
    `Checked: the copy was re-read${ocr ? ' with OCR' : ''} and none of the removed values can be recovered.` +
    (pixels ? ' Photos, QR codes and signatures were confirmed to be solid black.' : '')
  );
}

function importance(item: ResultItem): [number, number] {
  const idRank = ID_TYPES.indexOf(item.piiType);
  return [idRank === -1 ? ID_TYPES.length : idRank, -item.best.confidence];
}

/**
 * Collapses occurrences of the same value into one item: an Aadhaar number printed three times is one item that
 * appears three times. Government IDs come first, then everything else by confidence.
 */
export function groupFindings(findings: PublicFinding[]): ResultItem[] {
  const groups = new Map<string, PublicFinding[]>();
  for (const finding of findings) {
    const occurrences = groups.get(finding.group);
    if (occurrences) occurrences.push(finding);
    else groups.set(finding.group, [finding]);
  }
  const items = [...groups.entries()].map(([key, occurrences]): ResultItem => {
    const best = occurrences.reduce((top, finding) => (finding.confidence > top.confidence ? finding : top));
    const pages = [
      ...new Set(occurrences.map((finding) => finding.location.page).filter((page): page is number => page !== null)),
    ].sort((a, b) => a - b);
    return { key, piiType: best.piiType, maskedValue: best.maskedValue, best, occurrences, pages };
  });
  return items.sort((a, b) => {
    const [typeA, confidenceA] = importance(a);
    const [typeB, confidenceB] = importance(b);
    return typeA - typeB || confidenceA - confidenceB;
  });
}

export function idVerdict(item: ResultItem): IdVerdict {
  if (item.best.validationStatus === 'VALIDATED') return 'valid';
  if (item.best.validationStatus === 'FAILED_VALIDATION') return 'invalid';
  return 'unchecked';
}

export function idNoun(type: PIIType): string {
  return ID_NOUNS[type] ?? 'number';
}

/** Plain-language result of the structural check, per kind of identifier. */
export function verdictText(item: ResultItem): { title: string; detail: string } {
  const noun = idNoun(item.piiType);
  const checksum = CHECKSUM_TYPES.has(item.piiType);
  // A passport read from its machine-readable zone was checked against the ICAO 9303 check digit there.
  const mrz = item.occurrences.find((finding) => finding.reasons.some((reason) => reason.code === 'PASSPORT_MRZ_CHECK'));
  const mrzPassed = mrz?.reasons.some((reason) => reason.code === 'PASSPORT_MRZ_CHECK' && reason.passed) ?? false;
  switch (idVerdict(item)) {
    case 'valid':
      if (mrzPassed) {
        return {
          title: 'Valid number',
          detail: `Passes the check digit in the passport's machine-readable zone (ICAO 9303) and the ${noun} structure. A mistyped or made-up number almost always fails this check.`,
        };
      }
      return checksum
        ? {
            title: 'Valid number',
            detail: `Passes the official ${noun} checksum (Verhoeff) and structure rules. A mistyped or made-up number almost always fails this check.`,
          }
        : {
            title: 'Valid format',
            detail: `Follows the official ${noun} structure. There is no check digit, so this is a weaker test than for an Aadhaar number.`,
          };
    case 'invalid':
      return checksum
        ? {
            title: 'Not a valid number',
            detail: `Fails the official ${noun} checksum. It was mistyped, misread from the image, or is not a real ${noun}.`,
          }
        : {
            title: "Doesn't match the format",
            detail: `Doesn't follow the official ${noun} structure. It may be mistyped or misread.`,
          };
    case 'unchecked':
      return { title: 'Not checked', detail: `There is no structure check for this ${noun}.` };
  }
}

/** The checks run on the value itself (checksum, structure), leaving out how it was found. */
export function valueChecks(finding: PublicFinding): DetectionReason[] {
  return finding.reasons.filter((reason) => !DETECTION_CODES.has(reason.code));
}

/** "Page 1", "Page 1 · 3 times", "Pages 1 and 2 · 4 times" */
export function describeWhere(item: ResultItem): string {
  const pages =
    item.pages.length === 0
      ? ''
      : item.pages.length === 1
        ? `Page ${item.pages[0]}`
        : `Pages ${item.pages.slice(0, -1).join(', ')} and ${item.pages[item.pages.length - 1]}`;
  const times = item.occurrences.length > 1 ? pluralize(item.occurrences.length, 'time') : '';
  return [pages, times].filter(Boolean).join(' · ') || 'In the file';
}

/** "The file is", "Page 2 is", "Pages 1, 2 and 4 are": the subject of the unreadable-pages notice. */
export function unreadablePageText(pages: number[], totalPages?: number | null): string {
  if (pages.length === 0 || totalPages === 1) return 'The file is';
  if (pages.length === 1) return `Page ${pages[0]} is`;
  return `Pages ${pages.slice(0, -1).join(', ')} and ${pages[pages.length - 1]} are`;
}
