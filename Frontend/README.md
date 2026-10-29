# GovPII Guard

Detection of government-issued PII embedded in documents and data.
React 19 · TypeScript (strict) · Vite 7 · React Router 7 · CSS Modules · Vitest.

| Who                 | Where                     | What                                                                                                                             |
| ------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Anyone (no account) | `/` → `/results/:scanId`  | Upload one file, see masked findings and why they were flagged, download a verified redacted copy and a report, delete the file. |
| Administrators      | `/admin/login` → `/app/*` | Username + password. Dashboard, all documents (public and own uploads), findings, reports, audit log, settings, audited reveal.  |

There is no email anywhere — no email sign-in and no password-reset mail.

## Quick start

Run these in `Frontend/`:

```bash
npm install
npm run dev          # mock mode: an in-browser backend with sample data
npm run dev:api      # api mode: proxies /api to a FastAPI backend on :8000 (see .env.api)
```

Mock-mode administrator (shown on the sign-in page in mock mode only): username `admin`, password `GuardDemo#2026`.
In mock mode, file names containing `corrupt` simulate a failed scan and names containing `clean` produce no findings.

## Scripts

| Script              | Purpose                             |
| ------------------- | ----------------------------------- |
| `npm run typecheck` | `tsc -b` (strict, no `any`)         |
| `npm run lint`      | ESLint, zero warnings allowed       |
| `npm run test`      | Vitest + Testing Library (55 tests) |
| `npm run build`     | Type-check and production build     |
| `npm run format`    | Prettier                            |

## Architecture

```
src/
  app/          App, route table, route guards, providers (auth, toasts, preferences)
  components/   ui/ (primitives) · layout/ · navigation/ · documents/ · scans/ · findings/
                viewer/ · redaction/ · reports/ · audit/ · dashboard/ · settings/ · charts/ · brand/
  pages/        One lazily-loaded module per route
  services/     api.ts (the only HTTP client) + one typed service per domain
  hooks/        useResource (loading/success/error, abort, cache), useScan (polling), …
  types/        Domain models shared with the backend contract
  utils/        formatting, labels, validation, file checks, security helpers
  styles/       variables.css (all design tokens, light + dark), globals, utilities
  mocks/        Mock backend — dynamically imported only when VITE_API_MODE=mock
  test/         Test setup, render helpers, end-to-end journey test
```

- **One HTTP path.** Components never call `fetch`. Services call `api` ([src/services/api.ts](src/services/api.ts)), which centralises base URL, cookies, CSRF header, timeouts, error conversion and session-expiry handling.
- **Mock mode is a transport**, not fake data in components. It implements the same HTTP contract in the browser ([src/mocks/mockTransport.ts](src/mocks/mockTransport.ts)). Production builds (`.env.production` → `VITE_API_MODE=api`) compile it out; the build is verified to contain no mock code or sample data.
- **Failures are never shown as empty results.** `useResource` keeps `loading`, `success` and `error` distinct; every list page has separate empty, no-results and error states.
- **Design tokens only.** Every colour, space, radius and shadow comes from [src/styles/variables.css](src/styles/variables.css). Status is always colour + icon + text.

## Backend

The FastAPI backend lives in [../Backend/](../Backend/) — setup (native, no Docker), architecture, security model, configuration, deployment and evaluation are in [../Backend/README.md](../Backend/README.md). To run the app against it:

```bash
cd Backend && uvicorn app.main:app --host 127.0.0.1 --port 8000   # after the setup steps in Backend/README.md
cd Frontend && npm run dev:api                                    # in a second terminal
```

### Contract the frontend relies on

- **Base URL** `VITE_API_BASE_URL` (default `/api/v1`), same origin as the app (Vite proxies to `127.0.0.1:8000` in api mode).
- **Envelope.** Every JSON response is `{data, meta, error}`. `api.ts` unwraps `data`; `api.getPage()` maps list responses (`data` + `meta.page/pageSize/total`) to `Paginated<T>` `{items, page, pageSize, total}`.
- **Errors** are `{error: {code, message, details: [{field, message}], requestId}}`. The stable `code` decides the error kind (e.g. `DUPLICATE_DOCUMENT` → conflict, `UNSUPPORTED_FILE_TYPE` → validation), `details` become inline field errors, and `message` is shown only for 4xx when short and plain — never for 5xx. A bare FastAPI `{detail}` body is still understood.
- **Public pages** use no session. `POST /public/uploads` returns an access token once; [src/utils/publicAccess.ts](src/utils/publicAccess.ts) keeps it for that browser tab (`sessionStorage`), and [src/services/publicApi.ts](src/services/publicApi.ts) sends it as `X-Access-Token`. Public pages never call `/auth/*`: the administrator session is restored only when an admin route needs it.
- **Administrator sessions** are HTTP-only cookies; the frontend stores no session tokens. A `401` with `TOKEN_EXPIRED` triggers one silent `POST /auth/refresh` and a replay of the request; any other `401` (or a failed refresh) signs the user out with a "session expired" message. Mutating requests echo the `csrf_token` cookie in `X-CSRF-Token`.
- **Masking.** `Finding.maskedValue` is masked server-side; raw values come only from the audited `POST /findings/{id}/reveal`. Roles without `pii:reveal` receive page images with values already covered. Finding boxes are normalised to the page (`0–1`).
- UI role checks ([src/utils/security.ts](src/utils/security.ts)) mirror the backend for usability only; the backend enforces them.

Endpoints and types: the live OpenAPI docs at `http://127.0.0.1:8000/docs`, and [src/types/](src/types/) for the models the UI consumes.

## Testing

- Unit: file validation (extension, MIME, size, empty, magic bytes), masking, redirect safety, validation, formatting.
- API client: envelope unwrapping and pagination, error codes → kinds, 422 field errors, silent refresh + replay on `TOKEN_EXPIRED`, session-expiry broadcast, 403, 404, 500 (no leakage), FastAPI fallback, network failure, timeout, CSRF header.
- Components: Button, status badges, ConfirmDialog (focus, Escape), FileDropzone, FindingExplanation (masked, permission-gated reveal).
- Pages: administrator sign-in (username only, no email or reset options), Dashboard, Documents, Scan details, Findings — including empty, error and signed-out states.
- End-to-end journeys against the mock backend: public (upload → results → explanation → redacted copy → report → delete; no results without the tab's token) and administrator (sign in → upload → scan → viewer → redact → report → audit log → sign out).

## Notes

- Toolchain pinned to proven majors (Vite 7, React Router 7, TypeScript 5.9, ESLint 9, Vitest 3) rather than the newest releases.
- Large lists are paginated server-side; virtualization was not added because no page renders more than 100 rows.
- Interface preferences (theme, density) are stored in `localStorage` — they are non-sensitive. Public upload access tokens are kept in `sessionStorage` for the uploading tab only. Nothing else is persisted client-side.
