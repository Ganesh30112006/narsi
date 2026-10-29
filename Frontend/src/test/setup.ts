import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';
import { configureMock, resetMockState } from '../mocks/mockTransport';
import { invalidateResource } from '../hooks/useResource';

// jsdom gaps
if (!('createObjectURL' in URL)) {
  Object.defineProperty(URL, 'createObjectURL', { value: () => 'blob:mock', writable: true });
}
if (!('revokeObjectURL' in URL)) {
  Object.defineProperty(URL, 'revokeObjectURL', { value: () => undefined, writable: true });
}
Element.prototype.scrollIntoView = function scrollIntoView() {};
window.scrollTo = (() => undefined) as typeof window.scrollTo;
HTMLAnchorElement.prototype.click = function click() {};
// React Router builds a fetch Request for every navigation; Node's Request rejects jsdom's AbortSignal.
const NodeRequest = globalThis.Request;
globalThis.Request = class extends NodeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(input, init?.signal ? { ...init, signal: undefined } : init);
  }
} as typeof Request;

beforeEach(() => {
  configureMock({ latencyMs: 0 });
  resetMockState();
  invalidateResource('');
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
