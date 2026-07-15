# Xiaohongshu Metrics Collector Design

Date: 2026-07-05

Status: 已实施；本文保留作设计记录。

## Goal

Automatically collect performance metrics for published Xiaohongshu notes once per day, bind Xiaohongshu note identifiers to existing agent content records, and update both current metrics and daily history.

The collector must minimize creator-center access. It must not open individual notes, call undocumented internal APIs, bypass verification, spoof browser fingerprints, or retry aggressively.

## Confirmed Requirements

- Run daily at 22:00 in `Asia/Shanghai`.
- If the Mac misses the scheduled run because it is asleep or off, run once after the next wake or login.
- Allow at most one successful collection per local calendar day.
- Use a dedicated persistent Playwright browser profile outside the repository.
- The user completes login manually through an `auth` command.
- Export metrics from the official creator-center Excel file.
- Enter note management only when a database record is missing `post_id`.
- Read note IDs from note-list cards without opening note previews or detail pages.
- Generate the stable URL as `https://www.xiaohongshu.com/explore/{post_id}`.
- Use fuzzy title matching with publication time as secondary evidence.
- Skip ambiguous matches rather than writing to the wrong content record.
- Save all available Excel metrics and retain both latest values and daily snapshots.

## Existing Data Model

The existing identifiers have distinct meanings and must remain separate:

- `contents.content_id`: internal agent-generated primary key.
- `contents.post_id`: Xiaohongshu's stable note ID.
- `contents.url`: stable URL generated from `post_id`.
- `metrics.content_id`: foreign key to the internal `contents.content_id`.

The collector must never replace the internal `content_id` with a Xiaohongshu note ID.

## Architecture

The feature is an independent `metrics_collector` package with two commands:

```bash
python -m metrics_collector auth
python -m metrics_collector collect
```

The package contains these bounded components:

1. `BrowserSession`
   - Starts a headed Playwright browser with a dedicated persistent profile.
   - Checks whether creator-center authentication is valid.
   - Never stores or fills passwords, SMS codes, QR codes, or CAPTCHA answers.

2. `NoteIdentityCollector`
   - Queries only content records with a missing `post_id`.
   - Opens note management only when such records exist.
   - Reads note-card titles, publication times, and `noteId` values from list-card attributes.
   - Reads at most three list pages per run.
   - Never opens individual note previews or detail pages.
   - Generates `contents.url` from the matched `post_id`.

3. `MetricsExporter`
   - Opens the data-analysis page once per run.
   - Requests one official `笔记列表明细表.xlsx` export.
   - Waits for a completed `.xlsx` file and rejects temporary or incomplete downloads.

4. `MetricsWorkbookParser`
   - Validates the expected Chinese headers before producing records.
   - Converts placeholders, percentages, dates, and duration values to typed Python values.
   - Does not write to the database if workbook-level validation fails.

5. `ContentMatcher`
   - Matches note-list and workbook records to internal content records.
   - Returns explicit matched, unmatched, and ambiguous results.
   - Never silently chooses an ambiguous candidate.

6. `MetricsRepository`
   - Persists note bindings, current metrics, history snapshots, run status, and audit events.
   - Performs current-metric and history writes in one transaction.

7. `CollectionCoordinator`
   - Enforces access limits and the daily execution gate.
   - Runs every browser operation sequentially.
   - Stops immediately when authentication or risk-control signals appear.

## Collection Flow

1. Determine the local scheduled date in `Asia/Shanghai`.
2. Skip when a successful collection has already executed on the current local calendar date.
3. Create a collection-run record with status `running`.
4. Start the dedicated headed browser profile.
5. Validate creator-center authentication.
6. Query records missing `post_id`.
7. If records are missing `post_id`, read up to three note-management list pages and bind only confident matches.
8. Generate each matched URL from its `post_id`; do not open the note.
9. Open data analysis and export one Excel workbook.
10. Parse and validate the complete workbook before any metric write.
11. Match workbook rows to internal content records.
12. Atomically update current metrics and the daily history snapshot.
13. Record counts for exported, updated, skipped, ambiguous, and identity-bound rows.
14. Mark the run `success` or `partial_success`.
15. Delete a successfully imported temporary workbook and close the browser.

## Scheduling

Use a macOS LaunchAgent with a calendar trigger for 22:00 and a login/wake trigger. The collector itself is the source of truth for idempotency.

The run ledger stores both `scheduled_date` and the actual local `execution_date`. A successful run on an execution date prevents another automatic run that same local day. If the 22:00 run is missed, the next login or wake performs one catch-up run. An explicitly invoked diagnostic command may inspect state, but automatic failure retries are prohibited.

Both `success` and `partial_success` count as a completed daily run. Ambiguous rows therefore do not cause repeated browser access later the same day.

The LaunchAgent must run only inside the user's graphical login session because the collector uses a headed browser.

## Authentication

The dedicated browser profile defaults to a user-owned directory such as:

```text
~/.xhs-agent/browser-profile
```

The profile path and all browser state must be excluded from Git.

Authentication has no guaranteed lifetime. Each collection begins with a read-only login check. When authentication has expired, the run is marked `auth_required` and stops. The user restores the session by running the `auth` command and logging in manually.

## Access And Risk-Control Limits

- One metrics export per run.
- Zero individual note-preview or note-detail visits.
- Note management is skipped when no records are missing `post_id`.
- At most three note-management list pages per run.
- All browser operations are sequential.
- No parallel tabs, refresh loops, internal API calls, stealth plugins, fingerprint spoofing, CAPTCHA bypass, or automatic credential entry.
- No automatic retry after authentication failure, verification challenge, HTTP 401/403/429, unexpected redirect, or download failure.
- Browser actions use explicit state checks and bounded timeouts.
- Logs must not contain cookies, browser storage, credentials, or security tokens.

These controls reduce risk but cannot guarantee that Xiaohongshu will not request verification or invalidate a session.

## Matching

### Normalization

Titles are normalized using Unicode NFKC, whitespace collapsing, case normalization for Latin text, and removal of non-semantic punctuation. The original title is retained for audit output.

### Candidate Scoring

Matching uses the following order:

1. A unique exact normalized-title match is accepted.
2. Otherwise, candidates require a title similarity of at least `0.82`.
3. The combined score is `0.90 * title_similarity + 0.10 * time_score`.
4. Time scoring uses `published_at` when available and otherwise `created_at`:
   - within 24 hours: `1.0`
   - within 72 hours: `0.8`
   - within 7 days: `0.5`
   - within 30 days: `0.2`
   - over 30 days: `0.0`
5. The winning combined score must be at least `0.80`.
6. The winner must exceed the second candidate by at least `0.05`.

Multiple exact-title candidates use publication-time proximity to disambiguate. If the thresholds or margin are not satisfied, the row is marked ambiguous and skipped.

The numeric thresholds are configuration values with the defaults above. Lowering them requires an explicit configuration change, not an automatic retry strategy.

## Workbook Mapping

The workbook source columns map as follows:

| Excel column | Database field |
| --- | --- |
| 曝光 | `impressions` |
| 观看量 | `views` |
| 封面点击率 | `cover_click_rate` |
| 点赞 | `likes` |
| 评论 | `comments` |
| 收藏 | `saves` |
| 涨粉 | `followers_gained` |
| 分享 | `shares` |
| 人均观看时长 | `avg_watch_time_seconds` |
| 弹幕 | `danmaku_count` |

`-` and blank cells are treated as unavailable values during parsing. They must not silently overwrite an existing non-null value with zero. Explicit numeric zero remains zero.

For the latest `metrics` row, unavailable source fields retain their previous values. If no previous value exists, they remain `NULL`. The daily history row preserves unavailable source fields as `NULL` so it remains an accurate representation of that export. Derived rates and performance levels are recalculated from the merged latest values.

## Database Changes

### `metrics`

Add nullable fields:

```text
impressions INTEGER
cover_click_rate REAL
avg_watch_time_seconds INTEGER
danmaku_count INTEGER
```

Extend `MetricsRecord` and `update_metrics()` with optional parameters for these fields. Existing callers remain compatible. The current rate and performance-level calculations continue to use `views` and existing engagement fields.

### `metrics_history`

Add a daily snapshot table keyed by `(content_id, collected_date)`. It stores:

- all raw metric fields;
- calculated rates;
- performance level;
- collection timestamp;
- source identifier `creator_center_note_export_v1`;
- foreign key to `contents.content_id`.

An upsert for the same content and date replaces that day's snapshot rather than creating duplicates.

### `metrics_collection_runs`

Add a run-ledger table containing:

- `scheduled_date`;
- `execution_date`;
- `status`;
- start and completion timestamps;
- exported, updated, skipped, ambiguous, and identity-bound counts;
- a sanitized error summary.

The run ledger enforces daily idempotency and supports wake/login catch-up decisions.

### Transaction Boundaries

- Workbook parsing and validation complete before a metric transaction begins.
- Current metrics and daily history for the entire validated import are committed together.
- Any database error rolls back the full metric import.
- Note-identity bindings are written independently because they are valid even if a later workbook download fails.
- Audit events record successful bindings and metric imports without credentials or token data.

## Failure Handling

| Condition | Behavior |
| --- | --- |
| Login page or expired session | Mark `auth_required`; stop |
| CAPTCHA or verification challenge | Mark `verification_required`; stop |
| 401, 403, or 429 signal | Mark `blocked`; stop; no same-day automatic retry |
| Unexpected creator-center redirect | Mark failed; stop |
| Export timeout or incomplete file | Mark failed; do not update metrics |
| Missing or changed required headers | Preserve workbook in a restricted diagnostic directory; do not update metrics |
| Ambiguous row match | Skip row and record candidates and scores |
| Database write error | Roll back the metric batch |
| Temporary workbook cleanup failure | Record warning without rolling back imported data |

## File Handling

Successful imports delete the temporary workbook. Failed workbook validation preserves the file in a user-only diagnostic directory with restrictive permissions so it can be inspected manually. Old diagnostic files are deleted by a bounded retention policy.

## Testing

Automated tests must not access the real Xiaohongshu website.

Test coverage includes:

- Chinese workbook headers and field mapping;
- placeholders, blanks, explicit zero, percentages, dates, and watch durations;
- exact, fuzzy, time-assisted, ambiguous, and unmatched title cases;
- migration from the existing database schema;
- backward compatibility for existing `update_metrics()` calls;
- current metrics plus daily-history upsert behavior;
- transaction rollback for a batch failure;
- 22:00 scheduling, missed-run catch-up, and same-day idempotency;
- browser login-state detection;
- immediate stop on verification and risk-control fixtures;
- enforcement of zero note-detail visits and the three-page list limit;
- export timeout and malformed workbook behavior.

Browser tests use local HTML fixtures and a temporary persistent profile. A manual smoke test may run against the creator center only when explicitly initiated by the user.

## Acceptance Criteria

- One successful daily run updates all confidently matched metrics from the official workbook.
- A missed 22:00 run is collected after the next wake or login without creating a second successful run that local day.
- Existing internal `content_id` values and foreign-key relationships remain unchanged.
- Missing Xiaohongshu identities populate `post_id` and a generated stable URL without opening individual notes.
- Ambiguous matches never update content or metrics.
- Latest metrics and one idempotent daily snapshot are both available.
- Authentication or verification problems stop safely and require manual action.
- Automated tests make no real requests to Xiaohongshu.
