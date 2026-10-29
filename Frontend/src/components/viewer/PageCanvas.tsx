import type { CSSProperties } from 'react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ImageOff, RefreshCw, X } from 'lucide-react';
import { toApiError } from '../../services/apiError';
import { documentApi } from '../../services/documentApi';
import type { DocumentPage } from '../../types/document';
import type { Finding } from '../../types/finding';
import { formatPercent } from '../../utils/formatting';
import { PII_TYPE_LABELS } from '../../utils/labels';
import { FindingExplanation } from '../findings/FindingExplanation';
import { Button, IconButton } from '../ui/Button';
import { Skeleton } from '../ui/Skeleton';
import styles from './Viewer.module.css';

export type Rotation = 0 | 90 | 180 | 270;

interface PageCanvasProps {
  documentId: string;
  page: DocumentPage;
  findings: Finding[];
  zoom: number;
  rotation: Rotation;
  /** Cover detected values with opaque blocks. */
  obscure: boolean;
  selectedId: string | null;
  popoverOpen: boolean;
  onSelect(finding: Finding): void;
  onClosePopover(): void;
}

const POPOVER_MAX_HEIGHT = 380;

type ImageState = { status: 'loading' } | { status: 'ready'; url: string } | { status: 'error'; message: string };

/** Loads a page render as a Blob (so session cookies/CSRF apply) and exposes it as an object URL. */
function usePageImage(documentId: string, pageNumber: number) {
  const [state, setState] = useState<ImageState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let url: string | null = null;
    setState({ status: 'loading' });
    documentApi
      .getPageImage(documentId, pageNumber, controller.signal)
      .then((blob) => {
        url = URL.createObjectURL(blob);
        setState({ status: 'ready', url });
      })
      .catch((error: unknown) => {
        const apiError = toApiError(error);
        if (apiError.kind !== 'cancelled') setState({ status: 'error', message: apiError.message });
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [documentId, pageNumber, attempt]);

  return { state, retry: () => setAttempt((value) => value + 1) };
}

export function PageCanvas({
  documentId,
  page,
  findings,
  zoom,
  rotation,
  obscure,
  selectedId,
  popoverOpen,
  onSelect,
  onClosePopover,
}: PageCanvasProps) {
  const { state, retry } = usePageImage(documentId, page.pageNumber);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const highlightRefs = useRef(new Map<string, HTMLButtonElement>());
  const [popoverStyle, setPopoverStyle] = useState<CSSProperties | null>(null);
  const selected = findings.find((finding) => finding.id === selectedId) ?? null;
  const sideways = rotation === 90 || rotation === 270;

  // Position the popover next to the selected highlight (outside the rotated page so text stays upright).
  // It opens below the highlight, or above when the visible area below is too small.
  useLayoutEffect(() => {
    if (!popoverOpen || !selected) {
      setPopoverStyle(null);
      return;
    }
    const place = () => {
      const surface = surfaceRef.current;
      const viewport = surface?.parentElement;
      const target = highlightRefs.current.get(selected.id);
      if (!surface || !viewport || !target) return;
      const surfaceRect = surface.getBoundingClientRect();
      const viewportRect = viewport.getBoundingClientRect();
      const rect = target.getBoundingClientRect();
      const width = Math.min(340, surfaceRect.width - 16);
      const left = Math.min(Math.max(8, rect.left - surfaceRect.left), surfaceRect.width - width - 8);
      const spaceBelow = viewportRect.bottom - rect.bottom;
      const spaceAbove = rect.top - viewportRect.top;
      const above = spaceBelow < POPOVER_MAX_HEIGHT + 16 && spaceAbove > spaceBelow;
      const available = Math.max(160, (above ? spaceAbove : spaceBelow) - 24);
      setPopoverStyle(
        above
          ? {
              top: rect.top - surfaceRect.top - 8,
              left,
              width,
              maxHeight: Math.min(POPOVER_MAX_HEIGHT, available),
              transform: 'translateY(-100%)',
            }
          : { top: rect.bottom - surfaceRect.top + 8, left, width, maxHeight: Math.min(POPOVER_MAX_HEIGHT, available) },
      );
    };
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [popoverOpen, selected, zoom, rotation, state.status]);

  // Bring the selected highlight into view by scrolling only the viewer (never the page).
  useEffect(() => {
    if (!selectedId || state.status !== 'ready') return;
    const target = highlightRefs.current.get(selectedId);
    const viewport = surfaceRef.current?.parentElement;
    if (!target || !viewport) return;
    const targetRect = target.getBoundingClientRect();
    const viewportRect = viewport.getBoundingClientRect();
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const top = viewport.scrollTop + targetRect.top - viewportRect.top - viewportRect.height / 3;
    const left = viewport.scrollLeft + targetRect.left - viewportRect.left - viewportRect.width / 2 + targetRect.width / 2;
    if (typeof viewport.scrollTo === 'function') {
      viewport.scrollTo({ top, left, behavior: reduceMotion ? 'auto' : 'smooth' });
    } else {
      viewport.scrollTop = top;
      viewport.scrollLeft = left;
    }
  }, [selectedId, state.status, page.pageNumber]);

  const frameStyle: CSSProperties = {
    width: `${Math.round(zoom * 100)}%`,
    aspectRatio: sideways ? `${page.height} / ${page.width}` : `${page.width} / ${page.height}`,
  };
  const pageStyle: CSSProperties = sideways
    ? { width: `${(page.width / page.height) * 100}%`, transform: `translate(-50%, -50%) rotate(${rotation}deg)` }
    : { width: '100%', transform: `translate(-50%, -50%) rotate(${rotation}deg)` };

  return (
    <div className={styles.surface} ref={surfaceRef}>
      <div className={styles.frame} style={frameStyle}>
        <div
          className={styles.page}
          style={{ ...pageStyle, aspectRatio: `${page.width} / ${page.height}` }}
          data-obscured={obscure || undefined}
        >
          {state.status === 'loading' && <Skeleton width="100%" height="100%" radius={0} />}
          {state.status === 'error' && (
            <div className={styles.pageError} role="alert">
              <ImageOff size={20} aria-hidden />
              <p>This page couldn't be displayed.</p>
              <Button size="sm" icon={<RefreshCw size={14} aria-hidden />} onClick={retry}>
                Try again
              </Button>
            </div>
          )}
          {state.status === 'ready' && (
            <>
              <img src={state.url} alt={`Page ${page.pageNumber}`} className={styles.pageImage} draggable={false} />
              {findings.flatMap((finding) =>
                finding.location.boxes.map((box, index) => (
                  <button
                    key={`${finding.id}-${index}`}
                    ref={(element) => {
                      if (index !== 0) return;
                      if (element) highlightRefs.current.set(finding.id, element);
                      else highlightRefs.current.delete(finding.id);
                    }}
                    type="button"
                    className={[styles.highlight, finding.id === selectedId && styles.highlightSelected]
                      .filter(Boolean)
                      .join(' ')}
                    data-pii={finding.piiType}
                    data-redaction={finding.redactionState}
                    style={{
                      left: `${box.x * 100}%`,
                      top: `${box.y * 100}%`,
                      width: `${box.width * 100}%`,
                      height: `${box.height * 100}%`,
                    }}
                    aria-label={`${PII_TYPE_LABELS[finding.piiType]}, ${formatPercent(finding.confidence)} confidence. Show explanation.`}
                    aria-pressed={finding.id === selectedId}
                    tabIndex={index === 0 ? 0 : -1}
                    onClick={() => onSelect(finding)}
                  >
                    {obscure && index === 0 && <span className={styles.highlightTag}>{PII_TYPE_LABELS[finding.piiType]}</span>}
                  </button>
                )),
              )}
            </>
          )}
        </div>
      </div>

      {popoverOpen && selected && popoverStyle && (
        <div
          className={styles.popover}
          style={popoverStyle}
          role="dialog"
          aria-label={`${PII_TYPE_LABELS[selected.piiType]} explanation`}
        >
          <div className={styles.popoverHeader}>
            <span>Finding details</span>
            <IconButton label="Close explanation" size="sm" onClick={onClosePopover}>
              <X size={14} aria-hidden />
            </IconButton>
          </div>
          <FindingExplanation finding={selected} compact />
        </div>
      )}
    </div>
  );
}
