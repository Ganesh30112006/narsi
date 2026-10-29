import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { Logo } from '../brand/Logo';
import styles from './PublicLayout.module.css';

/** Frame for the public (no sign-in) pages: brand, a discreet administrator link and the privacy promise. */
export function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.page}>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <header className={styles.header}>
        <Link to="/" className={styles.brand} aria-label="GovPII Guard — scan a file">
          <Logo />
        </Link>
        <Link to="/admin/login" className={styles.adminLink}>
          Administrator sign in
        </Link>
      </header>
      <main id="main" className={styles.main}>
        {children}
      </main>
      <footer className={styles.footer}>
        <p>
          Files are checked automatically and deleted after 24 hours. Results show masked values only. Detection is automated and
          can miss or misjudge information — review the results before relying on them.
        </p>
      </footer>
    </div>
  );
}
