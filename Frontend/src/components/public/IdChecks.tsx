import type { LucideIcon } from 'lucide-react';
import { Check, ExternalLink, ShieldCheck, ShieldQuestion, ShieldX, X } from 'lucide-react';
import { PII_TYPE_LABELS } from '../../utils/labels';
import type { IdVerdict, ResultItem } from '../../utils/publicResults';
import { describeWhere, idVerdict, OFFICIAL_CHECKS, valueChecks, verdictText } from '../../utils/publicResults';
import type { BadgeTone } from '../ui/Badge';
import { Badge } from '../ui/Badge';
import styles from './IdChecks.module.css';

const VERDICT_STYLE: Record<IdVerdict, { tone: BadgeTone; icon: LucideIcon }> = {
  valid: { tone: 'success', icon: ShieldCheck },
  invalid: { tone: 'danger', icon: ShieldX },
  unchecked: { tone: 'neutral', icon: ShieldQuestion },
};

/** "Is this ID number valid?" — one card per distinct government ID found, with the checks behind the answer. */
export function IdChecks({ items }: { items: ResultItem[] }) {
  return (
    <div className={styles.wrap}>
      <ul className={styles.list}>
        {items.map((item) => {
          const verdict = idVerdict(item);
          const { tone, icon: Icon } = VERDICT_STYLE[verdict];
          const text = verdictText(item);
          const checks = valueChecks(item.best);
          const official = OFFICIAL_CHECKS[item.piiType];
          return (
            <li key={item.key} className={[styles.card, styles[verdict]].filter(Boolean).join(' ')}>
              <span className={styles.icon} aria-hidden>
                <Icon size={20} />
              </span>
              <div className={styles.body}>
                <div className={styles.heading}>
                  <h3 className={styles.title}>
                    {PII_TYPE_LABELS[item.piiType]}{' '}
                    <code className={styles.value} aria-label={`masked value ${item.maskedValue}`}>
                      {item.maskedValue}
                    </code>
                  </h3>
                  <Badge tone={tone}>{text.title}</Badge>
                </div>
                <p className={styles.where}>{describeWhere(item)}</p>
                <p className={styles.detail}>{text.detail}</p>
                {checks.length > 0 && (
                  <ul className={styles.checks} aria-label="Checks on the number">
                    {checks.map((check) => (
                      <li key={check.code} className={check.passed ? styles.passed : styles.failed}>
                        {check.passed ? <Check size={14} aria-hidden /> : <X size={14} aria-hidden />}
                        <span>
                          <span className="visually-hidden">{check.passed ? 'Passed: ' : 'Failed: '}</span>
                          {check.label}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {official && (
                  <p className={styles.official}>
                    {official.text}{' '}
                    <a href={official.href} target="_blank" rel="noopener noreferrer" className={styles.link}>
                      {official.site}
                      <ExternalLink size={12} aria-hidden />
                      <span className="visually-hidden"> (opens in a new tab)</span>
                    </a>
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      <p className={styles.note}>
        A valid number is correctly formed. It doesn't prove the document is genuine or that the number belongs to the person
        named on it — only the issuing authority can confirm that.
      </p>
    </div>
  );
}
