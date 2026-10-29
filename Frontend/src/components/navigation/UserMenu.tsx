import { ChevronDown, LogOut, Settings, User } from 'lucide-react';
import { useNavigate } from 'react-router';
import { useAuth } from '../../hooks/useAuth';
import { useToast } from '../../hooks/useToast';
import { initials } from '../../utils/formatting';
import { ROLE_LABELS } from '../../utils/labels';
import { Menu } from '../ui/Menu';
import styles from './Navigation.module.css';

export function UserMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { notify } = useToast();
  if (!user) return null;

  const signOut = async () => {
    try {
      await logout();
    } catch {
      notify({
        tone: 'warning',
        title: 'Signed out on this device',
        description: 'We could not reach the server to end the session.',
      });
    }
    navigate('/admin/login', { replace: true });
  };

  return (
    <Menu
      header={
        <>
          <div className={styles.menuName}>{user.name}</div>
          <div className={styles.menuRole}>{ROLE_LABELS[user.role]}</div>
        </>
      }
      items={[
        { id: 'profile', label: 'Profile', icon: <User size={15} aria-hidden />, onSelect: () => navigate('/app/profile') },
        {
          id: 'settings',
          label: 'Settings',
          icon: <Settings size={15} aria-hidden />,
          onSelect: () => navigate('/app/settings'),
        },
        {
          id: 'signout',
          label: 'Sign out',
          icon: <LogOut size={15} aria-hidden />,
          onSelect: () => void signOut(),
          separated: true,
        },
      ]}
      trigger={(props) => (
        <button type="button" className={styles.userButton} aria-label={`Account menu for ${user.name}`} {...props}>
          <span className={styles.avatar} aria-hidden>
            {initials(user.name)}
          </span>
          <span className={styles.userText}>
            <span className={styles.userName}>{user.name}</span>
            <span className={styles.userRole}>{ROLE_LABELS[user.role]}</span>
          </span>
          <ChevronDown size={14} className={styles.userChevron} aria-hidden />
        </button>
      )}
    />
  );
}
