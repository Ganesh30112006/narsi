import type { DragEvent } from 'react';
import { useId, useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import { ACCEPT_ATTRIBUTE, MAX_UPLOAD_BYTES, SUPPORTED_FORMATS_LABEL } from '../../utils/file';
import { formatBytes } from '../../utils/formatting';
import { Button } from '../ui/Button';
import styles from './Documents.module.css';

interface FileDropzoneProps {
  onFiles(files: File[]): void;
  disabled?: boolean;
  multiple?: boolean;
}

export function FileDropzone({ onFiles, disabled = false, multiple = true }: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const hintId = useId();

  const accept = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    onFiles(Array.from(list));
  };

  const onDragEnter = (event: DragEvent) => {
    event.preventDefault();
    if (disabled) return;
    depth.current += 1;
    setDragging(true);
  };

  const onDragLeave = (event: DragEvent) => {
    event.preventDefault();
    depth.current = Math.max(0, depth.current - 1);
    if (depth.current === 0) setDragging(false);
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    depth.current = 0;
    setDragging(false);
    if (!disabled) accept(event.dataTransfer.files);
  };

  return (
    <div
      className={[styles.dropzone, dragging && styles.dropzoneActive, disabled && styles.dropzoneDisabled]
        .filter(Boolean)
        .join(' ')}
      onDragEnter={onDragEnter}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      data-testid="dropzone"
    >
      <span className={styles.dropzoneIcon} aria-hidden>
        <Upload size={20} />
      </span>
      <p className={styles.dropzoneTitle}>
        {dragging
          ? multiple
            ? 'Release to add files'
            : 'Release to add the file'
          : multiple
            ? 'Drop documents here'
            : 'Drop a document here'}
      </p>
      <p className={styles.dropzoneOr}>or</p>
      <Button variant="secondary" onClick={() => inputRef.current?.click()} disabled={disabled} aria-describedby={hintId}>
        {multiple ? 'Choose files' : 'Choose a file'}
      </Button>
      <p id={hintId} className={styles.dropzoneHint}>
        {SUPPORTED_FORMATS_LABEL} · Up to {formatBytes(MAX_UPLOAD_BYTES)}
        {multiple ? ' each' : ''}
      </p>
      <input
        ref={inputRef}
        type="file"
        className="visually-hidden"
        accept={ACCEPT_ATTRIBUTE}
        multiple={multiple}
        tabIndex={-1}
        aria-hidden
        data-testid="file-input"
        onChange={(event) => {
          accept(event.target.files);
          event.target.value = '';
        }}
      />
    </div>
  );
}
