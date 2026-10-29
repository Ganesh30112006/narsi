# GovPII Guard — Backend

FastAPI service that finds government-issued PII (Aadhaar, its Virtual ID and enrolment number, PAN, passport, voter ID,
driving licence) and related personal data (names, addresses, dates and places of birth, phone numbers, emails, exam
roll numbers, identification marks) in uploaded documents, together with the visual personal data on identity
documents (face photos, QR codes and barcodes, signatures). It explains every finding and produces verified
sanitized copies.

There are two kinds of user:

- **The public** — no account, no sign-in. Anyone can upload a file and get its results: what was found (masked),
  why each item was flagged, a verified redacted copy and a report. Each upload is reachable only with the access
  token returned when it was uploaded, and it is deleted after 24 hours or as soon as the uploader asks.
- **Administrators** — the only accounts that sign in (username and password). They see every upload, the
  dashboard, findings, reports and the audit log, can reveal values (audited) and manage settings. There is no
  email anywhere: no email sign-in, no password-reset mail.

The detection engine (`app/processing/`) is an independent, synchronous Python core with no web, database or
queue dependencies. FastAPI, the database and the job runner are layers around it.

- [Run it locally](#run-it-locally-no-docker)
- [Architecture](#architecture)
- [Detection and confidence](#detection-and-confidence)
- [API contract](#api-contract)
- [Security model](#security-model)
- [Configuration](#configuration)
- [Production deployment](#production-deployment)
- [Backup, recovery and retention](#backup-recovery-and-retention)
- [Testing and quality gates](#testing-and-quality-gates)
- [Evaluation](#evaluation)
- [Known limitations](#known-limitations)

---

## Run it locally (no Docker)

Everything runs natively. The local defaults need no external servers: SQLite holds the data and jobs run on a
thread pool inside the API process.

**Prerequisites**

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12+ | [uv](https://docs.astral.sh/uv/) is the easiest way to get it |
| Tesseract OCR | 5.x | Optional but needed for images and scanned PDFs. Windows: UB Mannheim installer; macOS: `brew install tesseract`; Debian/Ubuntu: `apt install tesseract-ocr` |
| OpenCV | 4.10+ | Installed with the Python dependencies (`opencv-python-headless`); finds photos, QR codes and signatures |

```bash
cd Backend
uv venv --python 3.12 .venv            # or: python3.12 -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
uv pip install -e ".[dev]"             # or: pip install -e ".[dev]"
python -m spacy download en_core_web_md   # the default model; en_core_web_sm also works (lower name recall)
# Deep OCR for blurred, dark and photographed pages (optional). --no-deps: it would otherwise pull in the plain
# onnxruntime and opencv-python, which clash with onnxruntime-directml and opencv-python-headless.
uv pip install --no-deps "rapidocr_onnxruntime==1.4.4"   # or: pip install --no-deps ...

cp .env.example .env                   # then set JWT_SECRET and PII_HASH_KEY (see below)
alembic upgrade head                   # creates storage/govpii.db and seeds roles + settings
python scripts/create_admin.py --username admin --name "Your Name"   # prompts for a password

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Generate each secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`, using a different
value for each. If Tesseract isn't on `PATH`, set `TESSERACT_CMD` in `.env`.

Once the server is up:

- Interactive API docs: http://127.0.0.1:8000/docs (ReDoc at `/redoc`, schema at `/openapi.json`)
- Readiness: http://127.0.0.1:8000/health/readiness
- Frontend against this backend: in `../Frontend` run `npm run dev:api`. Vite proxies `/api` to
  `http://127.0.0.1:8000` (see `Frontend/.env.api`), so cookies stay same-origin. The public scanner is at `/`, the
  administrator sign-in at `/admin/login`.

Readiness reports `degraded` rather than failing if Tesseract, the spaCy model or OpenCV is missing. The affected
features are skipped and scans carry a warning. If the configured spaCy model isn't installed, `en_core_web_sm`
is used when available.

---

## Architecture

```
app/
  api/            FastAPI routers (v1), dependencies (auth, CSRF, RBAC, rate limits), error handlers
  core/           settings, enums/permissions, exceptions + error codes, security, logging, middleware
  db/             SQLAlchemy 2 models (15 tables) and session handling
  schemas/        Pydantic v2 request/response models (camelCase on the wire)
  services/       use cases: auth, users, documents, scans, findings, redactions, reports, dashboard, audit
  workers/        job dispatch (inline thread pool | Celery | eager) and Celery tasks
  processing/     the detection engine — no FastAPI/DB imports
    extractor/      PDF (PyMuPDF), DOCX, XLSX (openpyxl), CSV, TXT, JSON/XML (defusedxml), images
    ocr/            Tesseract wrapper + preprocessing, used per page when a PDF page has no text layer, or only a
                    scanner app's invisible OCR layer (then both readings are kept); pages are recognised in
                    parallel, and a passport's machine-readable zone gets a second, dedicated pass
    normalization/  offset-preserving normalization (every character maps back to the source)
    detection/      rules, context analyzer, NER (spaCy), validators, scoring, dedup, explanations
    visual/         photos, QR codes and barcodes, signatures on PDF pages and images (OpenCV)
    redaction/      true PDF redaction, format-specific redaction, mandatory post-verification
    rendering/      page images for the viewer (server-side masking for users without pii:reveal)
    reporting/      report model and JSON/CSV/PDF exporters
migrations/       Alembic (0001–0010)
scripts/          create_admin.py, generate_dataset.py, evaluate.py
tests/            unit, integration (real OCR/NER), API, security
dataset/          synthetic corpus (dev + held-out test) and evaluation results
```

**Scan pipeline** (`processing/pipeline.py`): validate → extract text (with OCR fallback per page) → normalize →
detect (rules + context + NER) → validate identifiers → score → deduplicate → explain → find photos, QR codes and
signatures (PDFs and images) → persist findings, report and per-stage metrics. Stage progress is written to the scan row, and the frontend polls
`GET /scans/{id}/status`.

What keeps it fast:
- **Parallel OCR.** Pages that need OCR are rendered one at a time (PyMuPDF isn't thread-safe) and recognised on a
  small thread pool (`OCR_WORKERS`, default: one per core, at most 4); Tesseract runs as a separate process, so
  the threads really run in parallel. At most that many rendered pages are held in memory. An 8-page scanned PDF
  went from 2.4 s to 1.1 s on the development machine (`python scripts/benchmark.py`).
- **Batched NER.** All pages go through spaCy in one `nlp.pipe` run instead of one call per page (40-page text PDF:
  0.58 s → 0.45 s).
- **No second OCR for redaction.** A scan leaves its extraction in a small in-memory cache (6 documents, 10 minutes,
  never written to disk; very large documents are skipped). A redacted copy requested soon after, which is the
  usual public flow, re-reads the original from there instead of running OCR again (~1 s saved per scanned page
  set). With Celery the cache is per process, so a redaction on another worker simply reads the file again.

**Reading blurred, dark and phone-photo images.** Every page is read plainly with Tesseract first. If it measures as
poor (Laplacian sharpness, brightness, contrast, noise) or the reading is unsure, other readings are made and the one
holding the most confidently-read text wins, but only if it beats the plain reading by 15% (a restoration can alter
a digit on a page that was already readable). A sharp, well-lit scan is read once, so clean input costs nothing
extra. What is tried depends on what is wrong with the page:

- **Deep OCR** (`processing/ocr/deep.py`): PP-OCR through RapidOCR, the PP-OCRv4 text detector with the **English
  PP-OCRv5 recogniser** (`model/en_PP-OCRv5_rec_mobile.onnx`, SHA256 `c3461add59bb4323…`). Its recogniser was trained
  on photographed text and holds up where Tesseract's falls apart; the English model keeps the spaces between words
  ("Place of Birth", not "PlaceofBirth" as the bundled Chinese+English one reads it), which the field-label matching
  needs. The **detector runs on the Intel Iris Xe GPU (DirectML) and the recogniser on the CPU**: the recogniser sees
  a different line width on every call, which makes DirectML recompile, so this split (1.1 s per ID-card image) is
  faster than either device alone (CPU 2.0 s, GPU 2.1 s). Boxes the detector cut from one printed row are joined back
  into one text line, and each word gets its share of the line's box. On a grainy, blurred phone photo it also reads
  copies shrunk to 1/2 and 1/3, which average the noise away and make the blur small relative to the letters.
  PP-OCR rates its own output far more confidently than Tesseract does, so a PP-OCR reading may replace a usable
  Tesseract reading (mean confidence 0.65 or more) only when it is itself at least 0.90 sure: on a dense real Aadhaar
  letter an 0.87-sure PP-OCR reading had won on score alone and lost an address block.
- **Learned restorer** (`processing/ocr/restorer.py`, `model/restorer.onnx`, 2.2 MB): a 560k-parameter U-Net that
  turns a dim, grainy page into a clean one for Tesseract. Tried only on dim or grainy pages that are not also blurred
  under the noise (there it misreads characters). It runs through ONNX Runtime on the **Iris Xe (DirectML)**, 0.12 s
  per 768 px tile, with a **CPU engine beside it** (0.6 s per tile) taking tiles from the same queue while enough are
  waiting. Trained by `scripts/train_restorer.py` on synthetic documents only (`dataset/train_synthetic`, seeds
  101–105, never the dev or test seeds), degraded on the fly by CPU worker processes. Training ran on the CPU:
  torch-directml works on the Iris Xe but trained ~6x slower (0.9 vs 6 patches/s), so the GPU does inference.
- **Classical** (`processing/ocr/enhance.py`, OpenCV): denoise → lighting (gamma, background flattening) → CLAHE →
  deskew → sharpen, and Richardson-Lucy deconvolution for blur.

Without a GPU everything falls back to the CPU; without RapidOCR or the model files, to the classical path. There is
no CUDA on this machine.

**Phone photos: orientation, size, unreadable pages.**

- *EXIF orientation.* Phones store a portrait photo sideways with an EXIF Orientation tag. Every image is opened
  through one function (`extractor/image.py: upright_frames`) that turns it the way a viewer shows it, for reading,
  visual detection, redaction and verification alike, and the redacted copy is saved upright without EXIF. Before
  this, a sideways phone photo came back with its values still readable *and* marked verified, because verification
  re-read it with the same mismatch.
- *Turned text* (a card photographed in portrait, a page scanned upside down; `ocr/orientation.py`). When the first
  plain reading is poor, or its words stand taller than wide (Tesseract reads quarter-turned text as vertical lines),
  PP-OCR reads a small copy at each of the four turns, counting only horizontal lines; a turn that reads clearly
  better wins. The page is read turned upright and every word box is mapped back onto the page as it is. Visual
  detection looks at the page turned the same way (faces and signature labels are only recognised upright).
  Tesseract's own orientation detection was measured and rejected: at a confidence that never turned an upright page
  wrongly, it fixed 37 of 144 turned dev pages.
- *Large photos* are read with their longest side capped at 3000 px, and the lighting correction and deconvolution
  were rewritten to work at that size (background estimated on a shrunk copy; separable Gaussian blurs for
  Richardson-Lucy, same output): a 12-megapixel photo went from 88 s to 7 s.
- *Unreadable pages.* A page read with low confidence is listed in the scan's `unreadablePages`. When nothing was
  found and pages were unreadable, the results page says "We couldn't read this file clearly" and tells the person not
  to treat the file as safe to share, instead of "No personal data found".
- *GPU safety.* The restorer and PP-OCR's detector each hold a DirectML session; two running at once from different
  threads could crash the process inside the driver with no Python error. One process-wide lock (`ocr/gpu.py`)
  serialises every DirectML run.
- Candidate readings of a poor page run in parallel (Tesseract with `OMP_THREAD_LIMIT=1`), and readiness
  (`/health/readiness`, `/api/v1/health`) reports `deep_ocr`, `restorer` and `gpu`; the administrator status line
  names any part that is degraded and why.

Recall of text values on degraded copies of the synthetic dev images (`python scripts/bench_degraded.py`, 117 values
per cell). Tesseract with the classical enhancements → the full pipeline:

| Degradation | 0.4 | 0.6 | 0.8 |
|---|---|---|---|
| clean | 0.98 → 0.98 | | |
| blur (defocus or motion) | 0.61 → **0.75** | 0.37 → **0.67** | 0.16 → **0.64** |
| dark (gamma + uneven light + noise) | 0.91 → **0.95** | 0.71 → **0.91** | 0.24 → **0.81** |
| phone photo (tilt + shadow + dim + blur + noise + JPEG) | 0.18 → **0.39** | 0.00 → 0.05 | 0.00 → 0.00 |
| shadow | 0.94 → 0.97 | 0.94 → 0.95 | 0.93 → 0.93 |
| noise + JPEG | 0.97 → 0.98 | 0.97 → 0.98 | 0.97 → 0.98 |
| low resolution | 0.98 → 0.98 | 0.98 → 0.98 | 0.95 → 0.96 |

Precision rises with recall on blur (0.59 → 0.94 at blur 0.8) and dark, but falls on photos (0.84 → 0.64 at photo
0.4). Of those photo false positives, most are real values misread by a character or two (`SOZCF2348T` for
`SDZCF2348T`) or garbled real names and addresses: they sit on genuine personal data, so they are still redacted,
but the value shown is not exact. A poor page takes 5–8 s (several readings).

On the held-out test split (seed 2026, not used for training or any tuning decision), recall goes: blur 0.8
0.15 → 0.60 (precision 0.55 → 0.90), blur 0.6 0.40 → 0.62, dark 0.8 0.23 → 0.88, dark 0.6 0.72 → 0.93, photo 0.4
0.16 → 0.46 (precision 0.63 → 0.72), clean 0.93 → 0.97.

**Limits:** a phone photo with everything wrong at once at severity 0.6 and above is where it stops: the text is
hardly legible to a person either, and nothing tried recovered more than a few values (deconvolution, denoising,
upscaling, thresholding, the learned restorer, and PP-OCR on full-size and shrunk copies). The result page then shows
fewer findings rather than guessing; retake those photos in even light, held steady. All figures come from synthetic
degradations; real phone photos were not used for training or tuning.

**Document type.** A small classifier (hashed character 3–5-grams, logistic regression, run in numpy) labels the
file Aadhaar, PAN, passport, voter ID, driving licence, certificate or other from its OCR text, and says nothing
below 0.55 probability. It was trained on synthetic and degraded text only; on 350 held-out samples it answered
311 with none wrong.

**Job execution** (`TASK_EXECUTION`):

| Mode | Use | Behaviour |
|---|---|---|
| `inline` (default) | local, small single-server installs | Thread pool inside the API process. At startup, never-started scans are queued again. Scans and redactions interrupted mid-flight are marked failed and retryable; they are not rerun automatically, so a document that crashed the process can't crash it on every start. Temp-file cleanup (hourly), expiry of public uploads (every 15 min) and the retention policy (every 6 h) run on an in-process timer. **Run a single uvicorn process in this mode.** |
| `celery` | production | RabbitMQ broker, Celery workers (`acks_late`, prefetch 1) and Celery beat for maintenance. The API only enqueues. |
| `eager` | tests only | Jobs run synchronously in the request. Rejected when `ENVIRONMENT=production`. |

Workers claim a scan with a conditional `UPDATE … WHERE status = 'QUEUED'`, so duplicate deliveries are no-ops.
Re-running a completed scan never duplicates findings.

**Document versioning:** each administrator upload is hashed with SHA-256. Re-uploading identical bytes returns
`409 DUPLICATE_DOCUMENT` with the existing document's id, and a new file with the same name becomes a new version.
Public uploads are never deduplicated or versioned against each other — they all belong to one internal account,
so doing so would link strangers' files or reveal that a file had been seen before. Sanitized copies are stored as
separate documents linked to their original. Originals are never modified.

---

## Detection and confidence

Each candidate carries evidence from up to four independent sources:

| Source | What it contributes |
|---|---|
| **Rules** | Structural patterns per type: Aadhaar 12 digits in 4-4-4 groups, Aadhaar Virtual ID (VID) 16 digits in 4-4-4-4 groups, Aadhaar enrolment number (4/5/5 digits), PAN `AAAAA9999A`, passport (including the machine-readable zone), EPIC voter ID, state-coded driving licences, Indian mobile numbers, email, PIN codes |
| **Context** | The nearest field label wins ("PAN", "Aadhaar No", "VID", "DOB", "C/O"…), respecting field separators and table headers. Negative labels ("Invoice No", "Order ID", "Account"; for names, place labels such as "State" and "District") penalise. ID-letter layouts: multi-line address blocks with part labels ("VTC:", "PO:", "District:", "PIN Code:"), a date printed above the holder's gender, labels above their values ("Father's Name", "Given Name(s)", "Certified that"), the addressee under "To" when an address or care-of line follows, labelled roll numbers, places of birth and identification marks, and further occurrences of a name already detected in the same document. **Echoes:** once a number is proven by a check digit (MRZ, Verhoeff), OCR-garbled copies of it on the same page (`Jt6147431` for `X6747431`) are found by an OCR-aware edit distance anchored on an exact head or tail, so the printed copy is redacted too |
| **NER** | spaCy `en_core_web_md` PERSON/GPE/LOC/DATE entities; the main signal for names and addresses. A "name" with no capital letter is never accepted |
| **Validation** | Verhoeff checksum for Aadhaar and VID; ICAO 9303 check digits for the passport number and date of birth in a passport's machine-readable zone; PAN holder-type letter; date sanity for DOB; state codes for DL. Checks *structure*, never whether the ID exists |

The score is an explicit, auditable formula (`detection/scoring/fusion.py`, weights in `scoring/profiles.py`):

```
raw = prior + w_pattern·pattern + w_context·context + w_validation·[validated] + w_ner·ner + w_repeat·repeated
      − w_negative·negative
if validation failed:  raw = min(raw, cap_with_context | cap_without_context)
if the text came from OCR:  raw *= ocr_floor + (1 − ocr_floor)·ocr_confidence
confidence = clamp(raw, 0, 1)        HIGH ≥ 0.85 · MEDIUM ≥ 0.60 · LOW otherwise
```

Every finding stores this breakdown, and its human-readable explanation is built only from evidence that was
actually present ("Matches the expected PAN structure", "Nearby label 'PAN'", "Checksum valid"…). Findings
below the organisation's reporting threshold (default 0.50, set in Settings) are not stored.

Role mailboxes at government domains (`help@uidai.gov.in`, `support@….nic.in`) are printed on every issued
document and are not reported as personal data. Words such as "Aadhaar", "Government" or "India" are never
accepted as part of a person's name.

**Visual personal data** (`processing/visual/`). PDF pages that place an image (or draw a QR code as vectors) and
every image are rendered at 200 dpi and analysed with OpenCV. Only locations are used; nothing is decoded.

| Kind | How it is found |
|---|---|
| **QR codes and barcodes** | OpenCV's QR and barcode detectors, and for codes too dense or blurred for them (an Aadhaar secure QR code has ~150 modules a side) a texture test: a solid square in which nearly every row and column switches between dark and light (≥ 15% of pixels each way; QR codes measure 21–25%, small print 8%, emblems 12%). Every candidate must also show at least two QR finder patterns (nested squares) in its corners, which removes look-alikes such as speckle noise |
| **Photos** | A face that two independent face models (OpenCV's frontal Haar cascades) both find, in a contrast-enhanced grey image or in the red channel, where the pale-blue "ghost" portrait on a passport stands out. The region is the embedded image holding the face when the PDF has one, otherwise the face widened to a portrait's proportions |
| **Signatures** | Ink strokes that aren't printed text or ruled lines, above, beside or below a "Signature" label (reported higher when the label says whose, e.g. "of the holder"), or below the portrait on a page with a passport machine-readable zone |

A visual finding stores a box, not a value; its keyed hash covers the type, page and box, and recovery checks it
before a redaction uses the box. Visual findings can't be revealed. In a redacted copy they are always solid black,
even with "mask" chosen.

**Government signatures** (`processing/authenticity/`). A visible seal, stamp or watermark in a picture cannot be
verified, because anyone can copy one. The one thing that can is a PDF's *digital signature* (DigiLocker documents,
eSign, signed government PDFs). Each signature is checked with pyHanko, offline, against the CCA India root
certificates and the licensed certifying authorities' certificates, downloaded from cca.gov.in and kept in
`authenticity/trust/` (`cca_india_roots.pem`, `licensed_cas.pem`). The result is one of: valid and unchanged,
changed after signing, signed by a certificate that does not lead to a CCA root, or not matching the document. It is
stored in the report summary and shown on the results page. Revocation is not checked (nothing is fetched while
scanning, so an uploaded file cannot make the server call out). A signing certificate whose issuing CA is not
bundled shows as "not recognised" until that CA certificate is added to `licensed_cas.pem`. Image signatures and
the Aadhaar secure QR code's own signature are not verified yet.

The detector version (`1.4.0+s<scoring fingerprint>+r<rule registry hash>`) is recorded on every scan and
report, so results can be traced to the exact weights and rules that produced them. No LLM is used anywhere.

**Privacy of stored results:** findings store only a masked value (`XXXXXX234F`) and a keyed HMAC-SHA-256 of
the value (`PII_HASH_KEY`). Raw values are never persisted or logged. When a permitted user reveals a value or
a redaction runs, the value is re-extracted from the stored original and checked against the stored hash.

**Redaction:** PDFs use true redaction (`apply_redactions`, including image pixels under the area), plus a
scrub of metadata, annotations and embedded files. Other formats are rewritten with the values replaced. When a
redacted value lies in a passport's machine-readable zone, every row of the zone is blacked out, because it also
encodes what isn't reported on its own (expiry date, the optional personal-number field, check digits). Every
sanitized copy is then **re-extracted, using OCR for images and scanned pages, and verified to contain none of
the removed values;** photos, QR codes and signatures are verified by rendering their regions and requiring them
to be solid black (method `…+pixels`). If verification fails, the redaction fails
(`REDACTION_VERIFICATION_FAILED`) and no file is released.

---

## API contract

Base path `/api/v1`. Every JSON response uses one envelope:

```json
{ "data": { }, "meta": { "page": 1, "pageSize": 20, "total": 57, "totalPages": 3 }, "error": null }
```

```json
{ "data": null, "meta": {}, "error": { "code": "DUPLICATE_DOCUMENT", "message": "This file has already been uploaded.",
  "details": [{ "field": "file", "message": "…" }], "requestId": "7f3c…" } }
```

- Fields are camelCase. List endpoints take `page` and `pageSize` (max 100) plus filters and `sortBy`/`sortOrder`.
- `error.code` is stable. Messages are safe to show, and 5xx responses never include internals. Every
  response has an `X-Request-ID` header, which also appears in the logs.
- Codes: `VALIDATION_ERROR`, `INVALID_CREDENTIALS`, `UNAUTHORIZED`, `TOKEN_EXPIRED`, `FORBIDDEN`, `CSRF_FAILED`,
  `NOT_FOUND`, `CONFLICT`, `DUPLICATE_DOCUMENT`, `DOCUMENT_TOO_LARGE`, `UNSUPPORTED_FILE_TYPE`, `INVALID_FILE`,
  `SCAN_IN_PROGRESS`, `SCAN_FAILED`, `OCR_FAILED`, `PROCESSING_TIMEOUT`, `REDACTION_FAILED`,
  `REDACTION_VERIFICATION_FAILED`, `VALUE_UNRECOVERABLE`, `RATE_LIMITED` (with `Retry-After`),
  `DEPENDENCY_UNAVAILABLE`, `SERVER_ERROR`.
- File downloads (documents, sanitized copies, report exports, page images) return raw bytes, not the envelope.

| Area | Endpoints |
|---|---|
| **Public** (no sign-in) | `POST /public/uploads` (multipart `file`) → `{scanId, accessToken, documentName, expiresAt}` · then, with header `X-Access-Token`: `GET /public/scans/{id}/status` · `GET /public/scans/{id}` (scan, masked findings, redaction, expiry) · `POST /public/scans/{id}/redaction` `{action: REDACT\|MASK}` · `GET /public/scans/{id}/redaction/download` · `GET /public/scans/{id}/report?format=pdf\|csv\|json` · `DELETE /public/scans/{id}` |
| Auth (admins) | `POST /auth/login` `{username, password}` · `POST /auth/refresh` · `POST /auth/logout` · `GET /auth/me` · `POST /auth/change-password` · `GET /auth/sessions` · `POST /auth/sessions/revoke-all` |
| Users (admins) | `PATCH /users/me` · `GET /users` · `POST /users` `{name, username, password}` (creates an administrator) · `PATCH /users/{id}` `{name?, isActive?}` |
| API keys (admins, signed in) | `GET /api-keys` · `POST /api-keys` `{name}` → the key, shown once · `DELETE /api-keys/{id}` |
| Documents | `GET/POST /documents` · `GET/DELETE /documents/{id}` · `GET /documents/{id}/download` · `/versions` · `/pages` · `/pages/{n}/image` |
| Scans | `POST /scans` · `GET /scans` · `GET /scans/{id}` · `GET /scans/{id}/status` · `POST /scans/{id}/retry` |
| Findings | `GET /findings` · `GET /findings/{id}` · `POST /findings/{id}/reveal` (reason required, audited) |
| Redactions | `POST /redactions` · `GET /redactions/{id}` · `GET /redactions/{id}/download` |
| Reports | `GET /reports` · `GET /reports/{id}` · `GET /reports/{id}/download?format=json\|csv\|pdf` |
| Dashboard | `GET /dashboard/summary` · `/dashboard/trends?days=` · `/dashboard/pii-distribution` |
| Settings / audit | `GET/PUT /settings` · `GET /audit-logs` (admin) |
| Health | `GET /health` · `/health/liveness` · `/health/readiness` (503 when a critical dependency is down) · `GET /api/v1/health` (for the web app) |

Reports and exports contain counts, types, locations, confidence levels and processing metrics. They never
contain detected values.

**Scanning from other systems.** An administrator creates a key under Settings → API keys and the other system
sends it as `Authorization: Bearer gpk_…`, with no cookies or CSRF token. A key works only on the Documents,
Scans, Findings, Redactions and Reports endpoints. It sees only documents its administrator owns (never public
uploads), and it can't reveal values, so findings stay masked. It also can't read the audit log or manage users,
settings or keys. Only the key's SHA-256 is stored. Revoking a key takes effect on the next request, and creating
or revoking one is audited.

```bash
curl -H "Authorization: Bearer $GOVPII_KEY" -F file=@form.pdf https://govpii.example/api/v1/documents
curl -H "Authorization: Bearer $GOVPII_KEY" -H "Content-Type: application/json"      -d '{"documentId":"<id>"}' https://govpii.example/api/v1/scans
```

---

## Security model

**Who can do what:**

| | Public visitor | Administrator |
|---|:-:|:-:|
| Upload a file; see its masked findings and why they were flagged | ✓ (own upload only, by token) | ✓ (every document) |
| Download a verified redacted copy and the report | ✓ (own upload only) | ✓ |
| Delete | ✓ (own upload only) | ✓ |
| Reveal a masked value (audited, reason required) | | ✓ |
| Dashboard, documents list, findings search, audit log, settings, administrator accounts | | ✓ |

**Administrators only sign in.** Login accepts a username and password and refuses every account that isn't an
active administrator — with the same "Incorrect username or password" as a wrong password. Access tokens and
refresh tokens of any other account are rejected too. Migration 0007 deactivates any older analyst/viewer
accounts and ends their sessions. There is no email address on accounts, no email sign-in and no password reset by
mail; a forgotten password is reset by someone with server access (`scripts/create_admin.py`, below).

**Public uploads.** Anonymous uploads are owned by a built-in account that cannot sign in (it has no valid
password hash). Each upload gets a fresh 256-bit token, returned once; only its SHA-256 is stored. Every public
request must send the token in `X-Access-Token` (a header, so it never lands in URLs, server logs or referrers). A
missing or wrong token, someone else's token, or an expired or deleted upload all get the same `404`. There is no
endpoint that lists public uploads. The browser keeps the token for that tab only (`sessionStorage`). Public
uploads get exactly the same file validation and processing limits as administrator uploads, are rate-limited
per IP (`RATE_LIMIT_PUBLIC_UPLOAD`, default 20 per hour), and are deleted — with their findings, reports and
redacted copies — after `PUBLIC_RETENTION_HOURS` (default 24) or immediately on `DELETE`. Public actions appear
in the audit log as "Public upload" with the client IP. `PUBLIC_UPLOADS_ENABLED=false` switches the whole public
side off (`404`).

**Scope:** inaccessible documents return `404`, not `403`, so the API doesn't reveal that a resource exists.
Scans, findings, redactions and reports inherit the document's scope. Page images and findings shown to the
public carry masked values only.

**Sessions and tokens:**
- Argon2id password hashes.
- A 15-minute JWT access token in an `HttpOnly; SameSite=Lax` cookie. The algorithm is pinned, and the token is
  bound to a refresh-token family that is checked against the database, so logout and revocation take effect
  immediately.
- A 7-day refresh token in an `HttpOnly; SameSite=Strict` cookie scoped to `/api/v1/auth`. It rotates on every
  use, and reusing an old one revokes the whole family.
- CSRF protection uses the double-submit pattern: a `csrf_token` cookie plus an `X-CSRF-Token` header on every
  mutating request.
- Changing your password ends your other sessions.

**Abuse controls:**
- Per-IP/per-user sliding-window rate limits (login, public upload and polling, upload, scan, redaction, report,
  reveal).
- Login lockout with exponential backoff, recorded in the database.
- Generic "Incorrect username or password" responses, so accounts can't be enumerated.

**Uploads:**
- Size limit enforced while streaming.
- Extension, MIME type and magic bytes must agree.
- Page, OCR-page and time limits.
- `defusedxml` with DTDs forbidden, zip-bomb checks for Office files, and `openpyxl` in read-only mode.
- Files are stored under random names with a path-traversal guard.

**HTTP headers:** strict CSP, `nosniff`, `no-store` on API responses, HSTS in production. CORS is an explicit
allow-list with credentials, and `TRUSTED_HOSTS` is enforced.

**Audit:** logins (including failures), uploads (public and administrator), scans, views, reveals, redactions,
exports, deletions (including automatic expiry), settings and administrator account changes. Entries never contain raw PII. Structured JSON logs scrub PII-shaped values as a
second line of defence.

---

## Configuration

All settings are environment variables, read from `.env` if present. `.env.example` documents every one. The
important ones:

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `production` enables startup checks (below) and HSTS |
| `DATABASE_URL` | `sqlite:///./storage/govpii.db` | PostgreSQL: `postgresql+psycopg://user:pass@host:5432/govpii` |
| `JWT_SECRET`, `PII_HASH_KEY` | — | Required, ≥ 32 chars, different from each other. **Changing `PII_HASH_KEY` makes existing findings unrecoverable** (reveal and redaction will refuse with `VALUE_UNRECOVERABLE`) |
| `COOKIE_SECURE` | `false` | Must be `true` behind HTTPS |
| `TASK_EXECUTION` | `inline` | `inline` \| `celery` |
| `CELERY_BROKER_URL` | — | `amqp://user:pass@host:5672//` |
| `MAX_UPLOAD_SIZE`, `MAX_PAGE_COUNT`, `MAX_OCR_PAGES`, `MAX_PROCESSING_SECONDS` | 50 MB, 500, 50, 300 | Processing limits |
| `OCR_ENABLED`, `TESSERACT_CMD`, `OCR_LANGUAGE` | `true`, PATH, `eng+hin+tel` | Language packs that aren't installed are skipped; readiness lists them. Each extra language slows OCR |
| `OCR_WORKERS` | `0` | Pages recognised in parallel; `0` = one per CPU core, at most 4 |
| `NER_ENABLED`, `SPACY_MODEL` | `true`, `en_core_web_md` | Falls back to `en_core_web_sm` when the model isn't installed |
| `VISUAL_DETECTION_ENABLED` | `true` | Photos, QR codes and barcodes, signatures in PDFs and images |
| `CORS_ALLOWED_ORIGINS`, `TRUSTED_HOSTS` | `http://localhost:5173`, `*` | Set both explicitly in production |
| `RATE_LIMIT_*` | e.g. `10/60` | `requests/seconds` |
| `PUBLIC_UPLOADS_ENABLED` | `true` | `false` turns off the public scanner |
| `PUBLIC_RETENTION_HOURS` | `24` | Public uploads and everything derived from them are deleted after this |
| `RATE_LIMIT_PUBLIC_UPLOAD`, `RATE_LIMIT_PUBLIC_POLL` | `20/3600`, `240/60` | Per client IP |
| `MAX_QUEUED_PUBLIC_SCANS` | `20` | Public scans waiting or running, across all visitors. Beyond it uploads get `503` with `Retry-After: 60`, and nothing is stored |
| `API_DOCS_ENABLED` | on outside production | Swagger UI, ReDoc and `/openapi.json`; off in production unless set to `true` |
| `BOOTSTRAP_ADMIN_USERNAME`, `BOOTSTRAP_ADMIN_PASSWORD` | — | Optional defaults for `scripts/create_admin.py` |

Organisation settings (reporting threshold, default redaction mode, retention days, automatic deletion) live
in the database and are edited by admins in the app (`PUT /settings`).

With `ENVIRONMENT=production`, startup **refuses to run** if:
- either secret is shorter than 32 characters, or the two secrets are identical;
- `COOKIE_SECURE` is false;
- CORS contains `*`;
- `TRUSTED_HOSTS` contains `*` (list the site's host names);
- `TASK_EXECUTION=eager`.

---

## Production deployment

These steps are native (systemd, NSSM or a similar process manager). No containers are required.

1. **PostgreSQL 14+.** Create a database and a least-privilege role, set `DATABASE_URL`, and run
   `alembic upgrade head` as part of every deployment. The migrations use portable types (JSONB on
   PostgreSQL, CHECK constraints instead of native enums) and add indexes for every list filter.
2. **RabbitMQ 3.12+** with a dedicated vhost and user. Set `TASK_EXECUTION=celery` and `CELERY_BROKER_URL`.
3. **API:** `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips 127.0.0.1`,
   run behind a TLS-terminating reverse proxy (nginx or IIS) on the same host. The proxy's body-size limit must be
   ≥ `MAX_UPLOAD_SIZE`. Per-visitor rate limits key on the client IP, so the proxy must set `X-Forwarded-For`, and
   `--forwarded-allow-ips` must name only the proxy: never `*`, or any client could pick its own IP. Without
   `--proxy-headers`, every visitor shares the proxy's IP and one busy visitor locks everyone out.
4. **Workers:** `celery -A app.workers.celery_app worker -Q scans,redactions,reports --concurrency 2`.
   OCR is CPU-bound, so size concurrency to cores. Add more worker hosts to scale; they need the same
   `UPLOAD_DIRECTORY` (shared volume) or a custom `StorageBackend`.
5. **Beat:** `celery -A app.workers.celery_app beat` runs exactly one instance. It schedules temp cleanup
   hourly, public-upload expiry every 15 min and the retention policy every 6 h on the `maintenance` queue, so also run a worker with
   `-Q maintenance`.
6. **Frontend:** in `Frontend/`, `npm run build` and serve `Frontend/dist/` from the same origin as `/api`, so the cookies stay
   first-party.
7. **Probes:** point liveness at `/health/liveness` and readiness at `/health/readiness`.

The rate limiter keeps its counters in memory, per process. With several API processes, the effective limit
multiplies by the process count. Login lockout is stored in the database, so it holds across processes.

---

## Backup, recovery and retention

- **What to back up:** the database *and* `UPLOAD_DIRECTORY` (originals and sanitized copies), taken together,
  plus `PII_HASH_KEY` and `JWT_SECRET` stored in your secret manager. Without `PII_HASH_KEY`, stored findings
  can still be listed, but values can no longer be revealed or redacted.
- **PostgreSQL:** use `pg_dump -Fc` nightly plus WAL archiving for point-in-time recovery. For SQLite, run
  `sqlite3 storage/govpii.db ".backup backup.db"` while the service is running; don't copy the file directly.
- **Restore:** restore the database and files from the same point in time, run `alembic upgrade head`, and start
  the service. In inline mode, scans that were queued are picked up again automatically. Interrupted ones show
  as failed with a **Retry** button.
- **Temp files:** each job works in a private temp directory that is removed when it finishes. A maintenance
  task removes anything older than an hour left behind by a crash.
- **Public uploads** expire after `PUBLIC_RETENTION_HOURS` (default 24), independently of the retention setting
  below. Uploads still being processed are skipped and picked up by the next run.
- **Retention:** when an admin enables automatic deletion, documents older than `retentionDays` are deleted
  together with their findings, reports and stored files. The audit trail is kept, with an entry per deletion.
  Manual deletion follows the same rules.

---

## Testing and quality gates

```bash
pytest                      # 162 tests (+3 on local real documents, below): unit, integration (real Tesseract + spaCy), API journeys, security
ruff check . && ruff format --check .
mypy app                    # strict
```

Tests run against a fresh migrated SQLite database with jobs in eager mode. Tests that need Tesseract or the
spaCy model are marked `ocr`/`ner`. The security suite covers:
- administrator-only sign-in (non-admin accounts and their tokens are refused) and anonymous access to admin
  endpoints (401);
- public uploads: token isolation (another upload's token, no token, made-up token → 404), no deduplication
  across strangers, same file validation, expiry purge, per-IP rate limit and the on/off switch;
- CSRF, and refresh-token reuse detection;
- lockout and rate limits;
- path traversal, magic-byte and MIME mismatches, zip bombs, and billion-laughs XML;
- security headers, error hygiene, and the absence of raw PII in API output, exports, audit entries,
  application logs and every database table.

---

## Evaluation

The evaluation uses a synthetic corpus generated by `scripts/generate_dataset.py`, with two disjoint splits,
each seeded separately:

| Split | Seed | Contents |
|---|---|---|
| `dev` | 7 | 76 documents, 80 pages, 613 labelled values, 12 labelled visual elements, 198 distractors. Used during development |
| `test` | 2030 | 76 documents, 80 pages, 617 labelled values, 12 labelled visual elements, 198 distractors. **Held out**: generated and evaluated once, after detector 1.4.0 was frozen |

Documents cover TXT, CSV, XLSX, JSON, XML, DOCX, text PDFs, scanned PDFs, clean images and noisy images, a
false-positive category, e-Aadhaar-style letters (text and scanned) with an enrolment number, the holder's name
under "To", a multi-line address block, the number and VID printed twice, the holder's name on both halves and, in
half of them, a date of birth whose label is missing; scanned passport data pages with labels above values, a place
of birth and a machine-readable zone; board certificates with names in capitals under their labels, a roll number
and identification marks listed around their label; and ID pages (scanned, photographed and digitally issued) with a
real QR code (dense or short), handwriting-like strokes over a "Signature of the holder" caption, and a seal-like
logo that must not be flagged. Distractors are look-alikes (invoice numbers, order IDs, 12-digit numbers with an
invalid checksum, label words, the issuer's help-desk email, passport issue and expiry dates, and school names).
The corpus has no faces (no synthetic face is realistic enough to be a fair test); photos are tested on the real
documents below.

```bash
python scripts/generate_dataset.py --split test --seed 2030
python scripts/evaluate.py --split test        # → dataset/results/test/{summary.md,summary.csv,per_type.csv,evaluation.json}
```

All experiments score the same extracted text, so only the detection configuration differs. Identifiers must
match exactly after canonicalization. Names and addresses match when their token sets have a Jaccard overlap of
at least 0.5; addresses must also share the PIN code. FPR is the share of distractors flagged. A visual detection
matches a labelled box of its type when it covers at least 90% of it and is at most four times its area; every
other visual detection, on any PDF or image in the corpus, is a false positive. Nothing is adjusted by hand.

**Held-out test split** (detector `1.4.0+s14e877c15bfa+r0a6bede1`, NER `en_core_web_md-3.8.0`):

| Experiment | Precision | Recall | F1 | FPR (distractors) | Detection ms/page |
|---|---|---|---|---|---|
| A — Rules only | 0.720 | 0.726 | 0.723 | 0.737 | 1.1 |
| B — Rules + Context | 0.988 | 0.960 | 0.974 | 0.020 | 2.6 |
| C — NER only | 0.886 | 0.201 | 0.328 | 0.000 | 13.9 |
| **D — Hybrid (production)** | **0.989** | **0.982** | **0.985** | **0.020** | 15.9 |

| Visual (33 PDF/image pages, 239 ms/page) | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| QR codes | 6 | 0 | 0 | 1.0 | 1.0 |
| Signatures | 6 | 0 | 0 | 1.0 | 1.0 |

Enrolment numbers, roll numbers, places of birth, identification marks, Aadhaar VIDs, PANs, voter IDs, driving
licences and addresses all score 1.0 precision and recall; the addressee names under "To" (missed by 1.3.0) are
all found. Extraction, including OCR, averaged 89 ms per page. The dev split gives D: P 0.990, R 0.995, F1 0.993,
and visual 12 of 12 with no false positives. Detection is slower than with 1.3.0 (16 ms/page against 14) because the
medium spaCy model is larger.

Each held-out split is used for exactly one detector version, then retired: 1.0.0 scored F1 0.988 on seed 2026,
1.1.0 0.991 on seed 2027, 1.2.0 0.988 on seed 2028, 1.3.0 0.987 on seed 2029. Later splits add categories, so the
numbers are not a trend; each is that version's score on data it had never seen.

**Where the hybrid engine is wrong on the test split** (all 18 errors, not a sample):
- **Four false positives are by design.** They are Aadhaar-shaped numbers under an "Aadhaar" label that fail
  the Verhoeff checksum. They are reported as LOW (0.52) rather than dropped, because a mistyped real Aadhaar
  number is still sensitive. Raising the reporting threshold above 0.52 removes them.
- **Eight errors are OCR misreads of the machine-readable zone on the three scanned passports:** two name lines
  were misread (`MENON<<KARIHIK` for `KARTHIK`), counting as two misses and two false positives; on one page the
  zone was unreadable (its copy of the number, the date of birth and the name were missed); one more date of birth
  in a zone was missed. Every value was still found in the visual zone, and a redaction blacks out all rows of the
  zone whatever OCR made of them.
- **One miss is a name in a prose sentence** ("…reviewed by Ananya Singh and forwarded…") that the language model
  didn't tag; there is no label to fall back on.
- **Five errors are OCR misses in images:** three email addresses and a phone number not read, and one email read
  without its first characters (one miss and one false positive).

**Real documents (local, never committed).** `tests/local/test_private_dataset.py` runs the production detector
over real documents in a local folder (default `../ML Training Dataset`, or `GOVPII_PRIVATE_DATASET`) and checks
them against an `expectations.json` written by hand after reviewing each document: which types must be found,
how often, whether they must pass validation, and which must not appear. Only types, counts and validation
outcomes are asserted, so neither the test nor its output contains the documents' values; it is skipped where the
folder doesn't exist. `python scripts/scan_folder.py <folder>` prints the masked findings for review. On the
current three documents (an e-Aadhaar letter, a passport data page photographed with a scanner app, and a board
certificate) every reviewed expectation passes: the enrolment number, roll number, identification marks and place
of birth; the passport number printed at the top of the photographed page, which both OCR readings garble and which
is found as an echo of the MRZ copy; and the visual elements — the passport portrait (with the holder's signature
on it) and its pale ghost portrait, the Aadhaar letter's two secure QR codes and photo, the certificate's photo and
QR code — with no false visual detections (the state emblem and logos are left alone). Redacted copies of all
three pass verification (OCR plus pixel checks); on the passport, every row of the machine-readable zone is
blacked out.

**Read these numbers with care.** The corpus is synthetic and templated: labels are clean, layouts are regular,
and the distractors were written by the same author as the rules. Real documents (handwriting, poor
scans, regional languages, free-form prose, unusual layouts) will perform worse, especially for names,
addresses and anything read by OCR. Treat these results as a regression baseline and a comparison between
components, not as an estimate of real-world accuracy. Measure on a representative, labelled sample of your own
documents before relying on the system.

---

## Known limitations

- **Not verified locally:**
  - **PostgreSQL** and **RabbitMQ/Celery** are supported through configuration and the portable migrations,
    but this build was developed and tested on SQLite with inline and eager jobs. Run the test suite and a
    smoke scan against both before a production rollout.
  - **Horizontal scaling** has not been load-tested. Performance figures above are from a single development
    machine.
- **Forgotten administrator passwords** can't be reset from the web app — there is deliberately no email. Someone
  with server access runs `python scripts/create_admin.py --username <name>`; for an existing account it sets
  the new password, clears any lockout and signs the account out everywhere.
- **Public result links work only in the uploading tab.** The access token lives in that tab's
  `sessionStorage`; closing the tab loses access to the results (the upload still expires on schedule). There is
  no way to recover a lost token, by design.
- **Public abuse protection:** a per-IP rate limit, the normal file limits and a global cap on queued public
  scans (`MAX_QUEUED_PUBLIC_SCANS`). There is no CAPTCHA, so a client using many IPs can still fill the queue and
  make other visitors wait (they get "try again in a minute", never an unbounded backlog). Put the service behind a
  reverse proxy with its own limits if it is exposed to the internet.
- **Languages:** English, Hindi and Telugu. Labels in Hindi and Telugu ("नाम", "पता", "జన్మ తేదీ", …), Indian-script
  digits, and the Hindi or Telugu copy of a name printed next to the English one are detected. Reading Hindi or
  Telugu from *images* needs Tesseract's `hin` / `tel` language packs (copy `hin.traineddata` and `tel.traineddata`
  from github.com/tesseract-ocr/tessdata_fast into Tesseract's `tessdata` folder). Without them, text PDFs and DOCX
  are still covered. Names written only in an Indian script, with no label and no English copy next to them, are
  missed, because the language model (NER) is English. Other Indian languages and handwriting are not supported.
- **Validation** checks structure and checksums only. It cannot tell whether an ID was actually issued.
- **Aadhaar Secure QR codes** are decoded (with zxing-cpp) and their RSA signature is checked offline against
  UIDAI's certificates in `app/processing/authenticity/trust/uidai_secure_qr.pem`. These are the offline e-KYC and
  Secure QR certificates from uidai.gov.in → Data and Downloads, including expired ones for older cards. A valid
  signature plus matching last four digits shows the QR code was issued for the printed number. A mismatch flags
  a possibly edited number. Nothing decoded from the QR code is stored. When UIDAI publishes a new certificate,
  append it to that file. Revocation isn't checked.
- **Visual detection is heuristic.** Faces must be roughly frontal and at least ~3% of the page's shorter side;
  a profile, a heavily obscured face or a very small thumbnail can be missed. Signatures are found only next to a
  "Signature" label or below a passport portrait, so an unlabelled signature elsewhere is missed. Fingerprints,
  holograms and other images (a photo of a house, a vehicle) are not looked for. DOCX, XLSX and other formats are
  not image-analysed. Check the redacted copy before sharing it.
- **Echo matching** finds OCR-garbled copies only of numbers proven by a check digit (passport MRZ, Aadhaar, VID)
  and only on OCR pages; a garbled copy of a number that appears nowhere in readable form is still missed.
- **Inline mode** is for a single process. Running several uvicorn workers with `TASK_EXECUTION=inline` would
  make each one's startup recovery fail the others' running jobs. Use Celery for more than one process.
