import type { LucideIcon } from 'lucide-react';
import { FileCode, FileImage, FileJson, FileSpreadsheet, FileText } from 'lucide-react';
import type { DocumentFileType } from '../../types/document';
import styles from './Documents.module.css';

const ICONS: Record<DocumentFileType, LucideIcon> = {
  PDF: FileText,
  DOCX: FileText,
  TXT: FileText,
  XLSX: FileSpreadsheet,
  CSV: FileSpreadsheet,
  JSON: FileJson,
  XML: FileCode,
  PNG: FileImage,
  JPG: FileImage,
  TIFF: FileImage,
};

export function FileTypeIcon({ type }: { type: DocumentFileType }) {
  const Icon = ICONS[type];
  return (
    <span className={styles.fileIcon} aria-hidden>
      <Icon size={16} strokeWidth={1.75} />
    </span>
  );
}
