import { Fragment } from 'react';

/**
 * Renders a file name with soft line-break opportunities after `_`, `-` and `.` so it wraps cleanly.
 * Assistive technology reads the unbroken name.
 */
export function FileName({ name }: { name: string }) {
  const parts = name.split(/(?<=[_.-])/);
  return (
    <>
      <span className="visually-hidden">{name}</span>
      <span aria-hidden>
        {parts.map((part, index) => (
          <Fragment key={index}>
            {part}
            {index < parts.length - 1 && <wbr />}
          </Fragment>
        ))}
      </span>
    </>
  );
}
