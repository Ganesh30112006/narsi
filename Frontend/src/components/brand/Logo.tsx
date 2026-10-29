import styles from './Logo.module.css';

export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden focusable="false" className={styles.mark}>
      <path d="M16 3.5 5.5 7.5v7.6c0 6.5 4.4 11.6 10.5 13.4 6.1-1.8 10.5-6.9 10.5-13.4V7.5L16 3.5Z" fill="var(--accent)" />
      <path d="M11.5 12.5h9M11.5 16h9M11.5 19.5h5.5" stroke="var(--surface)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

interface LogoProps {
  showSubtitle?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

export function Logo({ showSubtitle = false, size = 'md' }: LogoProps) {
  const markSize = size === 'lg' ? 36 : size === 'sm' ? 24 : 28;
  return (
    <span className={[styles.logo, styles[size]].join(' ')}>
      <LogoMark size={markSize} />
      <span className={styles.text}>
        <span className={styles.name}>GovPII Guard</span>
        {showSubtitle && <span className={styles.subtitle}>Privacy-aware document intelligence</span>}
      </span>
    </span>
  );
}
