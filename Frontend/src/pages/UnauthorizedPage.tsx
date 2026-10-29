import { Lock } from 'lucide-react';
import { LogoMark } from '../components/brand/Logo';
import { ButtonLink } from '../components/ui/Button';
import { useAuth } from '../hooks/useAuth';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { ROLE_LABELS } from '../utils/labels';
import styles from './AuthPages.module.css';

export default function UnauthorizedPage() {
  useDocumentTitle('Access restricted');
  const { user } = useAuth();

  return (
    <main className={[styles.standalone, styles.standaloneFull].join(' ')}>
      <LogoMark size={32} />
      <p className={[styles.code, styles.codeWithIcon].join(' ')}>
        <Lock size={12} aria-hidden />
        403 · Access restricted
      </p>
      <h1 className={styles.standaloneTitle}>You don't have access to this page</h1>
      <p className={styles.standaloneText}>
        {user && `Your role (${ROLE_LABELS[user.role]}) doesn't include access to this area. `}
        If you need access, contact your administrator.
      </p>
      <div className={styles.standaloneActions}>
        <ButtonLink to="/app/dashboard" variant="primary">
          Go to dashboard
        </ButtonLink>
      </div>
    </main>
  );
}
