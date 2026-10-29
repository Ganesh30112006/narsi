import type { KeyboardEvent, ReactNode } from 'react';
import { useId, useRef } from 'react';
import styles from './Misc.module.css';

interface SegmentedOption<V extends string> {
  value: V;
  label: string;
  icon?: ReactNode;
}

interface SegmentedControlProps<V extends string> {
  label: string;
  options: SegmentedOption<V>[];
  value: V;
  onChange(value: V): void;
  hideLabel?: boolean;
  disabled?: boolean;
}

/** A radio group rendered as segments; arrow keys move the selection. */
export function SegmentedControl<V extends string>({
  label,
  options,
  value,
  onChange,
  hideLabel,
  disabled,
}: SegmentedControlProps<V>) {
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const delta =
      event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0;
    if (!delta) return;
    event.preventDefault();
    const next = (index + delta + options.length) % options.length;
    const option = options[next];
    if (option) {
      onChange(option.value);
      refs.current[next]?.focus();
    }
  };

  return (
    <div className={styles.segmentedWrap}>
      <span id={id} className={hideLabel ? 'visually-hidden' : styles.segmentedLabel}>
        {label}
      </span>
      <div role="radiogroup" aria-labelledby={id} aria-disabled={disabled || undefined} className={styles.segmented}>
        {options.map((option, index) => {
          const checked = option.value === value;
          return (
            <button
              key={option.value}
              ref={(element) => {
                refs.current[index] = element;
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              tabIndex={checked ? 0 : -1}
              disabled={disabled}
              className={[styles.segment, checked && styles.segmentActive].filter(Boolean).join(' ')}
              onClick={() => onChange(option.value)}
              onKeyDown={(event) => onKeyDown(event, index)}
            >
              {option.icon}
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
