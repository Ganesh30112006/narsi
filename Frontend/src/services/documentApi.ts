import type { Paginated } from '../types/api';
import type { DocumentPage, DocumentQuery, DocumentRecord } from '../types/document';
import type { DownloadResult, QueryParams } from './api';
import { api } from './api';

export interface UploadDocumentOptions {
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
}

export interface DocumentService {
  list(query: DocumentQuery, signal?: AbortSignal): Promise<Paginated<DocumentRecord>>;
  get(documentId: string, signal?: AbortSignal): Promise<DocumentRecord>;
  upload(file: File, options?: UploadDocumentOptions): Promise<DocumentRecord>;
  remove(documentId: string): Promise<void>;
  download(documentId: string): Promise<DownloadResult>;
  listPages(documentId: string, signal?: AbortSignal): Promise<DocumentPage[]>;
  getPageImage(documentId: string, pageNumber: number, signal?: AbortSignal): Promise<Blob>;
}

const id = encodeURIComponent;

export const documentApi: DocumentService = {
  list: (query, signal) => api.getPage('/documents', { query: { ...query } as QueryParams, signal }),
  get: (documentId, signal) => api.get(`/documents/${id(documentId)}`, { signal }),
  upload: (file, options) => {
    const form = new FormData();
    form.append('file', file, file.name);
    return api.upload('/documents', form, { onProgress: options?.onProgress, signal: options?.signal });
  },
  remove: (documentId) => api.delete(`/documents/${id(documentId)}`),
  download: (documentId) => api.download(`/documents/${id(documentId)}/download`),
  listPages: (documentId, signal) => api.get(`/documents/${id(documentId)}/pages`, { signal }),
  getPageImage: async (documentId, pageNumber, signal) => {
    const { blob } = await api.download(`/documents/${id(documentId)}/pages/${pageNumber}/image`, { signal });
    return blob;
  },
};
