import { FileSearch } from 'lucide-react';
import type { Finding } from '../../types/finding';
import { PII_TYPE_LABELS } from '../../utils/labels';
import { ButtonLink } from '../ui/Button';
import { Drawer } from '../ui/Drawer';
import { FindingExplanation } from './FindingExplanation';

interface FindingDrawerProps {
  finding: Finding | null;
  onClose(): void;
}

export function FindingDrawer({ finding, onClose }: FindingDrawerProps) {
  return (
    <Drawer
      open={Boolean(finding)}
      onClose={onClose}
      title={finding ? `${PII_TYPE_LABELS[finding.piiType]} finding` : 'Finding'}
      subtitle={finding?.documentName}
      footer={
        finding && (
          <>
            <ButtonLink
              to={`/app/documents/${finding.documentId}?finding=${finding.id}`}
              variant="primary"
              icon={<FileSearch size={16} aria-hidden />}
            >
              Open in document
            </ButtonLink>
            <ButtonLink to={`/app/scans/${finding.scanId}`} variant="secondary">
              View scan
            </ButtonLink>
          </>
        )
      }
    >
      {finding && <FindingExplanation finding={finding} />}
    </Drawer>
  );
}
