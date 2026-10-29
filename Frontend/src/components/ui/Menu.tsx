import type { KeyboardEvent, ReactNode } from 'react';
import { useEffect, useId, useRef, useState } from 'react';
import styles from './Misc.module.css';

export interface MenuItem {
  id: string;
  label: string;
  icon?: ReactNode;
  onSelect(): void;
  danger?: boolean;
  disabled?: boolean;
  /** Render a divider above this item. */
  separated?: boolean;
}

interface MenuProps {
  /** Renders the trigger; spread `props` onto a button. */
  trigger(props: {
    ref: (element: HTMLButtonElement | null) => void;
    'aria-haspopup': 'menu';
    'aria-expanded': boolean;
    'aria-controls': string;
    onClick(): void;
    onKeyDown(event: KeyboardEvent<HTMLButtonElement>): void;
  }): ReactNode;
  items: MenuItem[];
  header?: ReactNode;
  align?: 'start' | 'end';
}

/** Accessible menu button: Enter/Space/ArrowDown opens, arrows move, Escape closes and returns focus. */
export function Menu({ trigger, items, header, align = 'end' }: MenuProps) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const enabled = items.map((item, index) => (item.disabled ? -1 : index)).filter((index) => index >= 0);

  const focusItem = (index: number | undefined) => {
    if (index === undefined) return;
    itemRefs.current[index]?.focus();
  };

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  const openMenu = (focus: 'first' | 'last') => {
    setOpen(true);
    window.requestAnimationFrame(() => focusItem(focus === 'first' ? enabled[0] : enabled[enabled.length - 1]));
  };

  const close = (restoreFocus = true) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  };

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openMenu('first');
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      openMenu('last');
    }
  };

  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const current = itemRefs.current.findIndex((element) => element === document.activeElement);
    const position = enabled.indexOf(current);
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusItem(enabled[(position + 1) % enabled.length]);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusItem(enabled[(position - 1 + enabled.length) % enabled.length]);
    } else if (event.key === 'Home') {
      event.preventDefault();
      focusItem(enabled[0]);
    } else if (event.key === 'End') {
      event.preventDefault();
      focusItem(enabled[enabled.length - 1]);
    } else if (event.key === 'Tab') {
      close(false);
    }
  };

  return (
    <div className={styles.menuContainer} ref={containerRef}>
      {trigger({
        ref: (element) => {
          triggerRef.current = element;
        },
        'aria-haspopup': 'menu',
        'aria-expanded': open,
        'aria-controls': menuId,
        onClick: () => (open ? close(false) : openMenu('first')),
        onKeyDown: onTriggerKeyDown,
      })}
      {open && (
        <div
          id={menuId}
          role="menu"
          className={[styles.menu, align === 'start' && styles.menuStart].filter(Boolean).join(' ')}
          onKeyDown={onMenuKeyDown}
        >
          {header && (
            <div className={styles.menuHeader} role="presentation">
              {header}
            </div>
          )}
          {items.map((item, index) => (
            <div key={item.id} role="none">
              {item.separated && <div className={styles.menuSeparator} role="separator" />}
              <button
                ref={(element) => {
                  itemRefs.current[index] = element;
                }}
                type="button"
                role="menuitem"
                tabIndex={-1}
                disabled={item.disabled}
                className={[styles.menuItem, item.danger && styles.menuItemDanger].filter(Boolean).join(' ')}
                onClick={() => {
                  close();
                  item.onSelect();
                }}
              >
                {item.icon}
                {item.label}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
