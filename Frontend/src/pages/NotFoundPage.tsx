import { ButtonLink } from '../components/ui/Button';
import { useAuth } from '../hooks/useAuth';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import styles from './AuthPages.module.css';

export default function NotFoundPage() {
  useDocumentTitle('Page not found');
  const { status } = useAuth();
  return (
    <div className={styles.standalone}>
      <p className={styles.code}>404</p>
      <h1 className={styles.standaloneTitle}>Page not found</h1>
      <p className={styles.standaloneText}>The page you're looking for doesn't exist or may have been moved.</p>
      <div className={styles.standaloneActions}>
        <ButtonLink to={status === 'authenticated' ? '/app/dashboard' : '/'} variant="primary">
          {status === 'authenticated' ? 'Go to dashboard' : 'Scan a file'}
        </ButtonLink>
      </div>
    </div>
  );
}
