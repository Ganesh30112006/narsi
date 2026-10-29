import type { FormEvent } from 'react';
import { useRef, useState } from 'react';
import { ArrowLeft, CircleAlert, Info } from 'lucide-react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { AuthLayout } from '../components/layout/AuthLayout';
import { Button } from '../components/ui/Button';
import { PasswordField, TextField } from '../components/ui/Field';
import { InlineNotice } from '../components/ui/StateViews';
import { useAuth } from '../hooks/useAuth';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { toApiError } from '../services/apiError';
import { safeRedirectPath } from '../utils/security';
import type { LoginFormErrors } from '../utils/validation';
import { hasErrors, validateLoginForm } from '../utils/validation';
import styles from './AuthPages.module.css';

function loginErrorMessage(error: unknown): string {
  const apiError = toApiError(error);
  switch (apiError.kind) {
    case 'unauthorized':
      return 'Incorrect username or password.';
    case 'rate_limited':
      return 'Too many sign-in attempts. Please wait a few minutes and try again.';
    case 'network':
    case 'timeout':
      return "We couldn't reach the server. Check your connection and try again.";
    case 'validation':
      return 'Check your username and password and try again.';
    default:
      return 'Sign-in is temporarily unavailable. Please try again shortly.';
  }
}

export default function LoginPage() {
  useDocumentTitle('Administrator sign in');
  const { login, sessionExpired } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<LoginFormErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    const validation = validateLoginForm(username, password);
    setErrors(validation);
    setFormError(null);
    if (hasErrors(validation)) {
      (validation.username ? usernameRef : passwordRef).current?.focus();
      return;
    }
    setSubmitting(true);
    try {
      await login({ username: username.trim(), password });
      navigate(safeRedirectPath(params.get('next')), { replace: true });
    } catch (error) {
      setFormError(loginErrorMessage(error));
      // Never keep a rejected password in memory longer than needed.
      setPassword('');
      passwordRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  };

  const canSubmit = username.trim().length > 0 && password.length > 0;

  return (
    <AuthLayout>
      <h1 className={styles.title}>Administrator sign in</h1>
      <p className={styles.subtitle}>For administrators only. To check a file, use the public scanner — no account needed.</p>

      {sessionExpired && !formError && (
        <div className={styles.notice}>
          <InlineNotice tone="warning">
            <Info size={16} aria-hidden />
            Your session has expired. Please sign in again.
          </InlineNotice>
        </div>
      )}

      {formError && (
        <div className={styles.notice}>
          <InlineNotice tone="danger">
            <CircleAlert size={16} aria-hidden />
            {formError}
          </InlineNotice>
        </div>
      )}

      <form className={styles.form} onSubmit={onSubmit} noValidate>
        <TextField
          ref={usernameRef}
          label="Username"
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          error={errors.username}
          autoFocus
          required
        />
        <PasswordField
          ref={passwordRef}
          label="Password"
          name="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={errors.password}
          required
        />
        <Button type="submit" variant="primary" fullWidth loading={submitting} loadingLabel="Signing in" disabled={!canSubmit}>
          Sign in
        </Button>
      </form>

      <p className={styles.secondaryAction}>
        <Link to="/" className={styles.backLink}>
          <ArrowLeft size={14} aria-hidden />
          Back to the public scanner
        </Link>
      </p>

      {import.meta.env.VITE_API_MODE === 'mock' && (
        <div className={styles.demo}>
          <p className={styles.demoTitle}>Mock mode — sample administrator</p>
          <p>
            Username: <code>admin</code>
          </p>
          <p>
            Password: <code>GuardDemo#2026</code>
          </p>
        </div>
      )}
    </AuthLayout>
  );
}
