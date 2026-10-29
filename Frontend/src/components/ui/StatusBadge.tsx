import type { LucideIcon } from 'lucide-react';
import {
  Ban,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  LoaderCircle,
  Minus,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react';
import type { AuditResult } from '../../types/audit';
import type { DocumentScanStatus } from '../../types/document';
import type { ConfidenceLevel, RiskLevel, ValidationStatus } from '../../types/finding';
import type { ScanStatus } from '../../types/scan';
import {
  AUDIT_RESULT_LABELS,
  CONFIDENCE_LABELS,
  DOCUMENT_STATUS_LABELS,
  RISK_LABELS,
  SCAN_STATUS_LABELS,
  VALIDATION_LABELS,
} from '../../utils/labels';
import type { BadgeTone } from './Badge';
import { Badge } from './Badge';

/**
 * The shared status vocabulary. Every status pairs a tone with an icon and a text label,
 * so meaning never relies on color alone.
 */
export type StatusKind =
  'high' | 'medium' | 'low' | 'validated' | 'processing' | 'queued' | 'failed' | 'completed' | 'idle' | 'warning' | 'denied';

const STATUS_STYLES: Record<StatusKind, { tone: BadgeTone; icon: LucideIcon; pulse?: boolean }> = {
  high: { tone: 'danger', icon: ShieldAlert },
  medium: { tone: 'warning', icon: TriangleAlert },
  low: { tone: 'neutral', icon: Minus },
  validated: { tone: 'success', icon: ShieldCheck },
  processing: { tone: 'accent', icon: LoaderCircle, pulse: true },
  queued: { tone: 'accent', icon: Clock },
  failed: { tone: 'danger', icon: CircleX },
  completed: { tone: 'success', icon: CircleCheck },
  idle: { tone: 'neutral', icon: CircleDashed },
  warning: { tone: 'warning', icon: TriangleAlert },
  denied: { tone: 'danger', icon: Ban },
};

interface StatusBadgeProps {
  status: StatusKind;
  label: string;
  title?: string;
}

export function StatusBadge({ status, label, title }: StatusBadgeProps) {
  const { tone, icon: Icon, pulse } = STATUS_STYLES[status];
  return (
    <Badge tone={tone} icon={<Icon size={12} strokeWidth={2} aria-hidden />} pulse={pulse} title={title}>
      {label}
    </Badge>
  );
}

const SCAN_KIND: Record<ScanStatus, StatusKind> = {
  QUEUED: 'queued',
  PROCESSING: 'processing',
  COMPLETED: 'completed',
  FAILED: 'failed',
  CANCELLED: 'idle',
};

export function ScanStatusBadge({ status }: { status: ScanStatus }) {
  return <StatusBadge status={SCAN_KIND[status]} label={SCAN_STATUS_LABELS[status]} />;
}

const DOCUMENT_KIND: Record<DocumentScanStatus, StatusKind> = {
  NOT_SCANNED: 'idle',
  QUEUED: 'queued',
  PROCESSING: 'processing',
  COMPLETED: 'completed',
  FAILED: 'failed',
};

export function DocumentStatusBadge({ status }: { status: DocumentScanStatus }) {
  return <StatusBadge status={DOCUMENT_KIND[status]} label={DOCUMENT_STATUS_LABELS[status]} />;
}

const CONFIDENCE_KIND: Record<ConfidenceLevel, StatusKind> = { HIGH: 'high', MEDIUM: 'medium', LOW: 'low' };

export function ConfidenceBadge({ level, short = false }: { level: ConfidenceLevel; short?: boolean }) {
  const label = short ? CONFIDENCE_LABELS[level].replace(' confidence', '') : CONFIDENCE_LABELS[level];
  return <StatusBadge status={CONFIDENCE_KIND[level]} label={label} title={CONFIDENCE_LABELS[level]} />;
}

const VALIDATION_KIND: Record<ValidationStatus, StatusKind> = {
  VALIDATED: 'validated',
  UNVALIDATED: 'idle',
  FAILED_VALIDATION: 'warning',
  NOT_APPLICABLE: 'low',
};

export function ValidationBadge({ status }: { status: ValidationStatus }) {
  return <StatusBadge status={VALIDATION_KIND[status]} label={VALIDATION_LABELS[status]} />;
}

const RISK_KIND: Record<RiskLevel, StatusKind> = { HIGH: 'high', MEDIUM: 'medium', LOW: 'low', NONE: 'completed' };

export function RiskBadge({ level }: { level: RiskLevel }) {
  const label = level === 'NONE' ? 'No PII' : `${RISK_LABELS[level]} risk`;
  return <StatusBadge status={RISK_KIND[level]} label={label} />;
}

const AUDIT_KIND: Record<AuditResult, StatusKind> = { SUCCESS: 'completed', FAILURE: 'failed', DENIED: 'denied' };

export function AuditResultBadge({ result }: { result: AuditResult }) {
  return <StatusBadge status={AUDIT_KIND[result]} label={AUDIT_RESULT_LABELS[result]} />;
}
