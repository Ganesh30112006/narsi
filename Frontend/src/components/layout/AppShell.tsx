import { Suspense, useEffect, useState } from 'react';
import { Menu as MenuIcon } from 'lucide-react';
import { Link, Outlet, useLocation } from 'react-router';
import { API_MODE } from '../../services/api';
import { Logo } from '../brand/Logo';
import { PrimaryNav, SecondaryNav } from '../navigation/NavLinks';
import { ServiceStatus } from '../navigation/ServiceStatus';
import { UserMenu } from '../navigation/UserMenu';
import { Badge } from '../ui/Badge';
import { IconButton } from '../ui/Button';
import { Drawer } from '../ui/Drawer';
import { PageSkeleton } from './PageSkeleton';
import styles from './AppShell.module.css';

export function AppShell() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();

  // Move focus to the main landmark on navigation so screen readers announce the new page.
  useEffect(() => {
    document.getElementById('main-content')?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  return (
    <div className={styles.shell}>
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>

      <header className={styles.topbar}>
        <div className={styles.topbarStart}>
          <IconButton label="Open navigation" className={styles.menuButton} onClick={() => setDrawerOpen(true)}>
            <MenuIcon size={18} aria-hidden />
          </IconButton>
          <Link to="/app/dashboard" className={styles.brandLink} aria-label="GovPII Guard home">
            <Logo size="sm" />
          </Link>
        </div>
        <div className={styles.topbarEnd}>
          {API_MODE === 'mock' && (
            <Badge tone="warning" title="Data is simulated in the browser. No backend is connected.">
              Mock data
            </Badge>
          )}
          <UserMenu />
        </div>
      </header>

      <nav className={styles.sidebar} aria-label="Main">
        <PrimaryNav />
        <div className={styles.sidebarFooter}>
          <SecondaryNav />
          <div className={styles.status}>
            <ServiceStatus />
          </div>
        </div>
      </nav>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title="Navigation" side="left" bare>
        <nav className={styles.drawerNav} aria-label="Main">
          <div className={styles.drawerBrand}>
            <Logo size="sm" showSubtitle />
          </div>
          <PrimaryNav onNavigate={() => setDrawerOpen(false)} />
          <div className={styles.drawerFooter}>
            <SecondaryNav onNavigate={() => setDrawerOpen(false)} />
            <ServiceStatus />
          </div>
        </nav>
      </Drawer>

      <main id="main-content" className={styles.main} tabIndex={-1}>
        <div className={styles.content}>
          <Suspense fallback={<PageSkeleton />}>
            <Outlet />
          </Suspense>
        </div>
      </main>
    </div>
  );
}
