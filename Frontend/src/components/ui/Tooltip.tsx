import type { ReactElement, ReactNode } from 'react';
import { cloneElement, useId } from 'react';
import styles from './Misc.module.css';

interface TooltipProps {
  content: ReactNode;
  /** A single focusable element; it receives aria-describedby. */
  children: ReactElement<{ 'aria-describedby'?: string }>;
}

/** Supplementary hint shown on hover and keyboard focus. Never the only source of meaning. */
export function Tooltip({ content, children }: TooltipProps) {
  const id = useId();
  return (
    <span className={styles.tooltipWrap}>
      {cloneElement(children, { 'aria-describedby': id })}
      <span role="tooltip" id={id} className={styles.tooltip}>
        {content}
      </span>
    </span>
  );
}
