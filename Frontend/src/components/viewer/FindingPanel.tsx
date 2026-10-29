import { ChevronDown, ChevronUp } from 'lucide-react';
import type { Finding } from '../../types/finding';
import { formatPercent } from '../../utils/formatting';
import { CONFIDENCE_SHORT_LABELS } from '../../utils/labels';
import { FindingBadge } from '../findings/FindingBadge';
import { IconButton } from '../ui/Button';
import styles from './Viewer.module.css';

interface FindingPanelProps {
  findings: Finding[];
  selectedId: string | null;
  currentPage: number;
  onSelect(finding: Finding): void;
}

/** Findings list beside the document. Selecting one jumps to its location. */
export function FindingPanel({ findings, selectedId, currentPage, onSelect }: FindingPanelProps) {
  const index = findings.findIndex((finding) => finding.id === selectedId);

  const step = (delta: number) => {
    if (findings.length === 0) return;
    const next = index === -1 ? (delta > 0 ? 0 : findings.length - 1) : (index + delta + findings.length) % findings.length;
    const finding = findings[next];
    if (finding) onSelect(finding);
  };

  return (
    <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <h2 className={styles.panelTitle}>
          Findings <span className={styles.panelCount}>{findings.length}</span>
        </h2>
        <div className={styles.panelNav}>
          <span className={styles.panelPosition} aria-live="polite">
            {index >= 0 ? `${index + 1} of ${findings.length}` : ''}
          </span>
          <IconButton label="Previous finding" size="sm" disabled={findings.length === 0} onClick={() => step(-1)}>
            <ChevronUp size={16} aria-hidden />
          </IconButton>
          <IconButton label="Next finding" size="sm" disabled={findings.length === 0} onClick={() => step(1)}>
            <ChevronDown size={16} aria-hidden />
          </IconButton>
        </div>
      </div>
      <ul className={styles.panelList}>
        {findings.map((finding) => {
          const active = finding.id === selectedId;
          const onPage = finding.location.page === currentPage;
          return (
            <li key={finding.id}>
              <button
                type="button"
                className={[styles.panelItem, active && styles.panelItemActive, !onPage && styles.panelItemOffPage]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() => onSelect(finding)}
                aria-current={active ? 'true' : undefined}
              >
                <span className={styles.panelItemTop}>
                  <FindingBadge type={finding.piiType} />
                  <span className={styles.panelPage}>Page {finding.location.page ?? '—'}</span>
                </span>
                <code className={styles.panelValue}>{finding.maskedValue}</code>
                <span className={styles.panelMeta}>
                  Confidence: {formatPercent(finding.confidence)}
                  <span className={styles.panelLevel} data-level={finding.confidenceLevel}>
                    {CONFIDENCE_SHORT_LABELS[finding.confidenceLevel]}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
