import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { forwardRef, useId, useState } from 'react';
import { CircleAlert, Eye, EyeOff } from 'lucide-react';
import styles from './Field.module.css';

interface FieldShellProps {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  optional?: boolean;
  hideLabel?: boolean;
  children: ReactNode;
  className?: string;
}

/** Label + control + hint + error, wired together with ids for assistive tech. */
export function FieldShell({ id, label, hint, error, optional, hideLabel, children, className }: FieldShellProps) {
  return (
    <div className={[styles.field, className].filter(Boolean).join(' ')}>
      <label htmlFor={id} className={hideLabel ? 'visually-hidden' : styles.label}>
        {label}
        {optional && <span className={styles.optional}>(optional)</span>}
      </label>
      {children}
      {hint && !error && (
        <span id={`${id}-hint`} className={styles.hint}>
          {hint}
        </span>
      )}
      {error && (
        <span id={`${id}-error`} className={styles.error}>
          <CircleAlert size={14} aria-hidden />
          {error}
        </span>
      )}
    </div>
  );
}

function describedBy(id: string, hint: unknown, error: unknown) {
  if (error) return `${id}-error`;
  if (hint) return `${id}-hint`;
  return undefined;
}

export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  optional?: boolean;
  hideLabel?: boolean;
  fieldClassName?: string;
}

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, hint, error, optional, hideLabel, id: providedId, className, fieldClassName, ...rest },
  ref,
) {
  const generated = useId();
  const id = providedId ?? generated;
  return (
    <FieldShell
      id={id}
      label={label}
      hint={hint}
      error={error}
      optional={optional}
      hideLabel={hideLabel}
      className={fieldClassName}
    >
      <input
        ref={ref}
        id={id}
        className={[styles.control, className].filter(Boolean).join(' ')}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        {...rest}
      />
    </FieldShell>
  );
});

export const PasswordField = forwardRef<HTMLInputElement, Omit<TextFieldProps, 'type'>>(function PasswordField(
  { label, hint, error, optional, id: providedId, className, fieldClassName, ...rest },
  ref,
) {
  const generated = useId();
  const id = providedId ?? generated;
  const [visible, setVisible] = useState(false);
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} optional={optional} className={fieldClassName}>
      <div className={styles.inputWrap}>
        <input
          ref={ref}
          id={id}
          type={visible ? 'text' : 'password'}
          className={[styles.control, className].filter(Boolean).join(' ')}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(id, hint, error)}
          autoCapitalize="off"
          spellCheck={false}
          {...rest}
        />
        <button
          type="button"
          className={styles.inputAddon}
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? 'Hide password' : 'Show password'}
          aria-pressed={visible}
          aria-controls={id}
        >
          {visible ? <EyeOff size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
        </button>
      </div>
    </FieldShell>
  );
});

export interface TextAreaFieldProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  optional?: boolean;
}

export function TextAreaField({ label, hint, error, optional, id: providedId, className, ...rest }: TextAreaFieldProps) {
  const generated = useId();
  const id = providedId ?? generated;
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} optional={optional}>
      <textarea
        id={id}
        className={[styles.control, className].filter(Boolean).join(' ')}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        {...rest}
      />
    </FieldShell>
  );
}

export interface SelectOption<V extends string = string> {
  value: V;
  label: string;
}

export interface SelectFieldProps<V extends string> extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange' | 'value'> {
  label: ReactNode;
  options: SelectOption<V>[];
  /** V is inferred from `options` only. */
  value: NoInfer<V> | '';
  onChange(value: NoInfer<V> | ''): void;
  /** Adds an "all" option with an empty value. */
  placeholder?: string;
  hint?: ReactNode;
  error?: string | null;
  hideLabel?: boolean;
  fieldClassName?: string;
}

/** Native select — the most accessible dropdown on every platform. */
export function SelectField<V extends string>({
  label,
  options,
  value,
  onChange,
  placeholder,
  hint,
  error,
  hideLabel,
  id: providedId,
  className,
  fieldClassName,
  ...rest
}: SelectFieldProps<V>) {
  const generated = useId();
  const id = providedId ?? generated;
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} hideLabel={hideLabel} className={fieldClassName}>
      <select
        id={id}
        className={[styles.control, styles.select, className].filter(Boolean).join(' ')}
        value={value}
        onChange={(event) => onChange(event.target.value as V | '')}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        {...rest}
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: ReactNode;
  description?: ReactNode;
  hideLabel?: boolean;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, description, hideLabel, className, ...rest },
  ref,
) {
  return (
    <label className={[styles.checkbox, className].filter(Boolean).join(' ')}>
      <input ref={ref} type="checkbox" {...rest} />
      <span className={hideLabel ? 'visually-hidden' : undefined}>
        {label}
        {description && <span className={styles.checkboxDescription}>{description}</span>}
      </span>
    </label>
  );
});

interface SwitchProps {
  label: ReactNode;
  description?: ReactNode;
  checked: boolean;
  onChange(checked: boolean): void;
  disabled?: boolean;
}

export function Switch({ label, description, checked, onChange, disabled }: SwitchProps) {
  const id = useId();
  return (
    <div className={styles.switchRow}>
      <div className={styles.switchText}>
        <div id={`${id}-label`} className={styles.label}>
          {label}
        </div>
        {description && (
          <div id={`${id}-description`} className={styles.hint}>
            {description}
          </div>
        )}
      </div>
      <button
        type="button"
        role="switch"
        className={styles.switch}
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        aria-describedby={description ? `${id}-description` : undefined}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      />
    </div>
  );
}
