import type { ReactNode } from 'react';
import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router';
import styles from './Misc.module.css';

interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  back?: { to: string; label: string };
  meta?: ReactNode;
}

export function PageHeader({ title, description, actions, back, meta }: PageHeaderProps) {
  return (
    <header className={styles.pageHeader}>
      {back && (
        <Link to={back.to} className={styles.backLink}>
          <ArrowLeft size={14} aria-hidden />
          {back.label}
        </Link>
      )}
      <div className={styles.pageHeaderRow}>
        <div className={styles.pageHeaderText}>
          <h1 className={styles.pageTitle}>{title}</h1>
          {description && <p className={styles.pageDescription}>{description}</p>}
          {meta && <div className={styles.pageMeta}>{meta}</div>}
        </div>
        {actions && <div className={styles.pageActions}>{actions}</div>}
      </div>
    </header>
  );
}

interface SectionProps {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
  /** Draw the heading rule (default). */
  ruled?: boolean;
}

/** Heading + hairline + content. Preferred over wrapping everything in cards. */
export function Section({ title, description, actions, children, id, ruled = true }: SectionProps) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section className={styles.section} aria-labelledby={headingId}>
      <div className={[styles.sectionHeader, ruled && styles.sectionRuled].filter(Boolean).join(' ')}>
        <div>
          <h2 id={headingId} className={styles.sectionTitle}>
            {title}
          </h2>
          {description && <p className={styles.sectionDescription}>{description}</p>}
        </div>
        {actions && <div className={styles.sectionActions}>{actions}</div>}
      </div>
      {children}
    </section>
  );
}

interface StatProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  emphasis?: 'danger' | 'default';
}

export function StatCard({ label, value, hint, emphasis = 'default' }: StatProps) {
  return (
    <div className={styles.stat}>
      <dt className={styles.statLabel}>{label}</dt>
      <dd className={[styles.statValue, emphasis === 'danger' && styles.statDanger].filter(Boolean).join(' ')}>{value}</dd>
      {hint && <dd className={styles.statHint}>{hint}</dd>}
    </div>
  );
}

export function StatGroup({ children, label }: { children: ReactNode; label: string }) {
  return (
    <dl className={styles.statGroup} aria-label={label}>
      {children}
    </dl>
  );
}

export function FilterBar({ children, onClear, canClear }: { children: ReactNode; onClear?: () => void; canClear?: boolean }) {
  return (
    <div className={styles.filterBar}>
      {children}
      {onClear && canClear && (
        <button type="button" className={styles.clearFilters} onClick={onClear}>
          Clear filters
        </button>
      )}
    </div>
  );
}

export interface DescriptionItem {
  label: string;
  value: ReactNode;
}

export function DescriptionList({ items, columns = 1 }: { items: DescriptionItem[]; columns?: 1 | 2 }) {
  return (
    <dl className={[styles.descriptionList, columns === 2 && styles.descriptionListTwo].filter(Boolean).join(' ')}>
      {items.map((item) => (
        <div key={item.label} className={styles.descriptionItem}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
