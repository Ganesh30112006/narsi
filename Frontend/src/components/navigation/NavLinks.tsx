import { NavLink } from 'react-router';
import { useAuth } from '../../hooks/useAuth';
import type { NavItem } from './navItems';
import { PRIMARY_NAV, SECONDARY_NAV } from './navItems';
import styles from './Navigation.module.css';

function NavList({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  const { can } = useAuth();
  return (
    <ul className={styles.list}>
      {items
        .filter((item) => !item.permission || can(item.permission))
        .map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              onClick={onNavigate}
              title={label}
              className={({ isActive }) => [styles.link, isActive && styles.active].filter(Boolean).join(' ')}
            >
              <Icon size={16} strokeWidth={1.75} aria-hidden />
              <span>{label}</span>
            </NavLink>
          </li>
        ))}
    </ul>
  );
}

export function PrimaryNav({ onNavigate }: { onNavigate?: () => void }) {
  return <NavList items={PRIMARY_NAV} onNavigate={onNavigate} />;
}

export function SecondaryNav({ onNavigate }: { onNavigate?: () => void }) {
  return <NavList items={SECONDARY_NAV} onNavigate={onNavigate} />;
}
