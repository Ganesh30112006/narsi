import type { ReactNode } from 'react';
import { EyeOff, ScrollText, ShieldCheck } from 'lucide-react';
import { Logo } from '../brand/Logo';
import styles from './AuthLayout.module.css';

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.page}>
      <aside className={styles.intro}>
        <Logo size="lg" showSubtitle />
        <div className={styles.introBody}>
          <p className={styles.headline}>Detect sensitive government-issued information before it leaves your systems.</p>
          <ul className={styles.points}>
            <li>
              <ShieldCheck size={16} aria-hidden />
              Aadhaar, PAN, passport, driving licence and voter ID detection
            </li>
            <li>
              <EyeOff size={16} aria-hidden />
              Values are masked by default
            </li>
            <li>
              <ScrollText size={16} aria-hidden />
              Every access is recorded in the audit log
            </li>
          </ul>
        </div>
        <p className={styles.footnote}>Authorised personnel only.</p>
      </aside>
      <main className={styles.formArea}>
        <div className={styles.mobileBrand}>
          <Logo showSubtitle />
        </div>
        <div className={styles.formInner}>{children}</div>
      </main>
    </div>
  );
}
