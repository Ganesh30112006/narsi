import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { forwardRef } from 'react';
import type { LinkProps } from 'react-router';
import { Link } from 'react-router';
import styles from './Button.module.css';
import { Spinner } from './Spinner';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'dangerOutline';
export type ButtonSize = 'sm' | 'md';

interface CommonProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  trailingIcon?: ReactNode;
  fullWidth?: boolean;
}

function classes(variant: ButtonVariant, size: ButtonSize, fullWidth: boolean | undefined, extra?: string) {
  return [styles.button, styles[variant], size === 'sm' && styles.sm, fullWidth && styles.fullWidth, extra]
    .filter(Boolean)
    .join(' ');
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, CommonProps {
  loading?: boolean;
  /** Announced to screen readers while loading. */
  loadingLabel?: string;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    icon,
    trailingIcon,
    fullWidth,
    loading = false,
    loadingLabel,
    disabled,
    className,
    children,
    type = 'button',
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={classes(variant, size, fullWidth, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Spinner size={size === 'sm' ? 12 : 14} label={loadingLabel} /> : icon}
      {children}
      {!loading && trailingIcon}
    </button>
  );
});

export interface ButtonLinkProps extends LinkProps, CommonProps {}

/** A router link styled as a button — for navigation actions. */
export function ButtonLink({
  variant = 'secondary',
  size = 'md',
  icon,
  trailingIcon,
  fullWidth,
  className,
  children,
  ...rest
}: ButtonLinkProps) {
  return (
    <Link className={classes(variant, size, fullWidth, className)} {...rest}>
      {icon}
      {children}
      {trailingIcon}
    </Link>
  );
}

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Required: icon-only buttons must be labelled. */
  label: string;
  size?: ButtonSize;
  bordered?: boolean;
  children: ReactNode;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, size = 'md', bordered, className, children, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={[styles.iconButton, size === 'sm' && styles.sm, bordered && styles.bordered, className]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      {children}
    </button>
  );
});
