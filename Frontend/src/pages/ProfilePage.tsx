import { Check, Minus } from 'lucide-react';
import { RecentActivity } from '../components/dashboard/RecentActivity';
import { ButtonLink } from '../components/ui/Button';
import { DescriptionList, PageHeader, Section } from '../components/ui/Layout';
import { SkeletonBlock } from '../components/ui/Skeleton';
import { ErrorState } from '../components/ui/StateViews';
import { useAuth } from '../hooks/useAuth';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useResource } from '../hooks/useResource';
import { auditApi } from '../services/auditApi';
import type { Permission } from '../types/auth';
import { formatDate, formatDateTime, initials } from '../utils/formatting';
import { ROLE_LABELS } from '../utils/labels';
import { PERMISSION_LABELS, hasPermission } from '../utils/security';
import styles from './ProfilePage.module.css';

export default function ProfilePage() {
  useDocumentTitle('Profile');
  const { user, can } = useAuth();
  const canReadAudit = can('audit:read');
  const activity = useResource(
    `profile-activity:${user?.id ?? ''}`,
    (signal) => auditApi.list({ userId: user?.id, pageSize: 8 }, signal),
    { enabled: Boolean(user && canReadAudit) },
  );

  if (!user) return null;

  return (
    <>
      <PageHeader
        title="Profile"
        description="Your identity and what your role allows."
        actions={
          <ButtonLink to="/app/settings" variant="secondary">
            Edit in settings
          </ButtonLink>
        }
      />

      <div className={styles.identity}>
        <span className={styles.avatar} aria-hidden>
          {initials(user.name)}
        </span>
        <div>
          <p className={styles.name}>{user.name}</p>
          <p className={styles.email}>@{user.username}</p>
        </div>
      </div>

      <div className={styles.grid}>
        <Section title="Account" id="profile-account">
          <div className={styles.pad}>
            <DescriptionList
              items={[
                { label: 'Role', value: ROLE_LABELS[user.role] },
                { label: 'Member since', value: formatDate(user.createdAt) },
                { label: 'Last sign-in', value: formatDateTime(user.lastLoginAt) },
              ]}
            />
          </div>
        </Section>

        <Section title="Permissions" id="profile-permissions" description="Enforced by the server on every request.">
          <ul className={styles.permissions}>
            {(Object.keys(PERMISSION_LABELS) as Permission[]).map((permission) => {
              const allowed = hasPermission(user.role, permission);
              return (
                <li key={permission} data-allowed={allowed}>
                  {allowed ? <Check size={14} aria-hidden /> : <Minus size={14} aria-hidden />}
                  <span>
                    {PERMISSION_LABELS[permission]}
                    <span className="visually-hidden">{allowed ? ' — allowed' : ' — not allowed'}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </Section>
      </div>

      {canReadAudit && (
        <Section title="Your recent activity" id="profile-activity">
          {activity.status === 'error' && activity.error ? (
            <ErrorState error={activity.error} subject="your activity" onRetry={activity.reload} compact />
          ) : !activity.data ? (
            <div className={styles.pad}>
              <SkeletonBlock lines={4} label="Loading activity" />
            </div>
          ) : activity.data.items.length === 0 ? (
            <p className={[styles.pad, 'muted'].join(' ')}>No activity recorded yet.</p>
          ) : (
            <RecentActivity entries={activity.data.items} />
          )}
        </Section>
      )}
    </>
  );
}
