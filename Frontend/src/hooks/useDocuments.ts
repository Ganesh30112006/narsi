import { documentApi } from '../services/documentApi';
import type { DocumentQuery } from '../types/document';
import { useResource } from './useResource';

export function useDocuments(query: DocumentQuery) {
  return useResource(`documents:${JSON.stringify(query)}`, (signal) => documentApi.list(query, signal));
}

export function useDocument(documentId: string | undefined) {
  return useResource(`document:${documentId ?? ''}`, (signal) => documentApi.get(documentId ?? '', signal), {
    enabled: Boolean(documentId),
  });
}
