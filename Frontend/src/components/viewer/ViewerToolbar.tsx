import { ChevronLeft, ChevronRight, EyeOff, Eye, RotateCw, ZoomIn, ZoomOut } from 'lucide-react';
import { IconButton } from '../ui/Button';
import { Tooltip } from '../ui/Tooltip';
import styles from './Viewer.module.css';

interface ViewerToolbarProps {
  page: number;
  pageCount: number;
  onPageChange(page: number): void;
  zoom: number;
  onZoomChange(zoom: number): void;
  onRotate(): void;
  obscure: boolean;
  /** Only offered to users allowed to see raw values. */
  onToggleObscure?: () => void;
}

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2;
const ZOOM_STEP = 0.25;

export function ViewerToolbar({
  page,
  pageCount,
  onPageChange,
  zoom,
  onZoomChange,
  onRotate,
  obscure,
  onToggleObscure,
}: ViewerToolbarProps) {
  return (
    <div className={styles.toolbar} role="toolbar" aria-label="Document controls">
      <div className={styles.toolbarGroup}>
        <IconButton label="Previous page" size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          <ChevronLeft size={16} aria-hidden />
        </IconButton>
        <span className={styles.pageIndicator} aria-live="polite">
          Page {page} / {pageCount}
        </span>
        <IconButton label="Next page" size="sm" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>
          <ChevronRight size={16} aria-hidden />
        </IconButton>
      </div>

      <div className={styles.toolbarGroup}>
        <IconButton
          label="Zoom out"
          size="sm"
          disabled={zoom <= MIN_ZOOM}
          onClick={() => onZoomChange(Math.max(MIN_ZOOM, zoom - ZOOM_STEP))}
        >
          <ZoomOut size={16} aria-hidden />
        </IconButton>
        <Tooltip content="Reset to fit width">
          <button
            type="button"
            className={styles.zoomValue}
            onClick={() => onZoomChange(1)}
            aria-label={`Zoom ${Math.round(zoom * 100)}%. Reset zoom`}
          >
            {Math.round(zoom * 100)}%
          </button>
        </Tooltip>
        <IconButton
          label="Zoom in"
          size="sm"
          disabled={zoom >= MAX_ZOOM}
          onClick={() => onZoomChange(Math.min(MAX_ZOOM, zoom + ZOOM_STEP))}
        >
          <ZoomIn size={16} aria-hidden />
        </IconButton>
        <span className={styles.toolbarDivider} aria-hidden />
        <IconButton label="Rotate page" size="sm" onClick={onRotate}>
          <RotateCw size={16} aria-hidden />
        </IconButton>
        {onToggleObscure && (
          <IconButton
            label={obscure ? 'Show detected values on page' : 'Cover detected values'}
            size="sm"
            onClick={onToggleObscure}
            aria-pressed={!obscure}
          >
            {obscure ? <Eye size={16} aria-hidden /> : <EyeOff size={16} aria-hidden />}
          </IconButton>
        )}
      </div>
    </div>
  );
}
