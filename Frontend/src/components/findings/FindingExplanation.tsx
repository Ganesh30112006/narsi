import { Check, X } from 'lucide-react';
import type { Finding } from '../../types/finding';
import { describeLocation, detectedBy } from '../../utils/findings';
import { formatDateTime } from '../../utils/formatting';
import { PII_TYPE_DESCRIPTIONS, REDACTION_STATE_LABELS } from '../../utils/labels';
import { ConfidenceBadge, ValidationBadge } from '../ui/StatusBadge';
import { ConfidenceIndicator } from './ConfidenceIndicator';
import { FindingBadge } from './FindingBadge';
import { MaskedValue } from './MaskedValue';
import styles from './Findings.module.css';

interface FindingExplanationProps {
  finding: Finding;
  /** Compact variant for popovers. */
  compact?: boolean;
}

/** Explains why something was flagged, without exposing the raw value. */
export function FindingExplanation({ finding, compact = false }: FindingExplanationProps) {
  return (
    <div className={compact ? styles.explanationCompact : styles.explanation}>
      <div className={styles.explanationHeader}>
        <FindingBadge type={finding.piiType} />
        <ConfidenceBadge level={finding.confidenceLevel} />
      </div>

      {!compact && <p className={styles.explanationDescription}>{PII_TYPE_DESCRIPTIONS[finding.piiType]}</p>}

      <dl className={styles.facts}>
        <div>
          <dt>Value</dt>
          <dd>
            <MaskedValue finding={finding} />
          </dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>
            <ConfidenceIndicator confidence={finding.confidence} level={finding.confidenceLevel} />
          </dd>
        </div>
        <div>
          <dt>Detected by</dt>
          <dd>{detectedBy(finding)}</dd>
        </div>
        <div>
          <dt>Validation</dt>
          <dd>
            <ValidationBadge status={finding.validationStatus} />
          </dd>
        </div>
        <div>
          <dt>Location</dt>
          <dd>{describeLocation(finding.location)}</dd>
        </div>
        {!compact && (
          <>
            <div>
              <dt>Redaction</dt>
              <dd>{REDACTION_STATE_LABELS[finding.redactionState]}</dd>
            </div>
            <div>
              <dt>Detected</dt>
              <dd>{formatDateTime(finding.createdAt)}</dd>
            </div>
          </>
        )}
      </dl>

      <div className={styles.reasons}>
        <h3 className={styles.reasonsTitle}>Why this was flagged</h3>
        <ul>
          {finding.reasons.map((reason) => (
            <li key={reason.code} className={reason.passed ? styles.reasonPassed : styles.reasonFailed}>
              {reason.passed ? <Check size={14} aria-hidden /> : <X size={14} aria-hidden />}
              <span>
                <span className="visually-hidden">{reason.passed ? 'Passed: ' : 'Not met: '}</span>
                {reason.label}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {!compact && finding.contextSnippet && (
        <div className={styles.context}>
          <h3 className={styles.reasonsTitle}>Context</h3>
          <p className={styles.contextSnippet}>{finding.contextSnippet}</p>
        </div>
      )}
    </div>
  );
}
