import type { ReactNode } from 'react';
import styles from './Settings.module.css';

interface SettingsSectionProps {
  id: string;
  title: string;
  description?: ReactNode;
  children: ReactNode;
}

/** Title + description on the left, controls on the right. Stacks on narrow screens. */
export function SettingsSection({ id, title, description, children }: SettingsSectionProps) {
  return (
    <section className={styles.section} aria-labelledby={`${id}-title`} id={id}>
      <div className={styles.intro}>
        <h2 id={`${id}-title`} className={styles.title}>
          {title}
        </h2>
        {description && <p className={styles.description}>{description}</p>}
      </div>
      <div className={styles.body}>{children}</div>
    </section>
  );
}
