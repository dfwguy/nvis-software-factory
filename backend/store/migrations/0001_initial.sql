-- 0001_initial — repositories, assessments, evidence, findings, and the LLM provenance record.
--
-- Design notes that are not obvious from the DDL:
--
-- * Ids are text UUIDs, minted by the application. Not integer autoincrement, because these ids
--   appear in URLs, in downloadable artifacts, and in another team's agent transcript, and a
--   sequential integer leaks how many assessments exist and invites enumeration.
--
-- * Timestamps are ISO-8601 UTC text, not unixepoch. SQLite has no date type either way, and text
--   means a human reading the file with `sqlite3` sees a timestamp rather than an integer they
--   have to convert. Sorts correctly as text because the format is fixed-width.
--
-- * `llm_calls` stores the RAW response, not just the parsed result. It is the single most useful
--   row in the schema when an assessment says something surprising: it answers "what did the model
--   actually return" without re-running anything, which a re-run cannot do at temperature > 0.
--
-- * Findings record `origin` and `escalated_from`. That pair is the ratchet's audit trail: it is
--   what lets a reviewer see that the model raised a scanner's `minor` to `blocker` and check
--   whether it was right, rather than being presented with a merged severity and no history.

CREATE TABLE repositories (
    id              TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    -- Normalized form used for dedup: lowercased, scheme and credentials and .git suffix removed.
    -- A separate column rather than a computed comparison so it can carry a UNIQUE index; three
    -- spellings of the same repository should not become three repositories.
    canonical_url   TEXT NOT NULL UNIQUE,
    forge           TEXT NOT NULL,       -- gitlab | github | other
    namespace       TEXT,
    name            TEXT NOT NULL,
    default_branch  TEXT,
    added_at        TEXT NOT NULL,
    added_by        TEXT NOT NULL,
    notes           TEXT
);

CREATE INDEX idx_repositories_added_at ON repositories(added_at DESC);

CREATE TABLE assessments (
    id                  TEXT PRIMARY KEY,
    repository_id       TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    -- queued | cloning | scanning | reasoning | rendering | complete | failed | cancelled
    status              TEXT NOT NULL,
    -- Set when status is 'failed'. A run that failed with no reason recorded is a run nobody can
    -- act on, so the application refuses to write that combination.
    failure_reason      TEXT,
    failure_detail      TEXT,
    -- Whether a retry can succeed without a change. An unreachable LLM endpoint is retryable; a
    -- repository that does not exist is not.
    retryable           INTEGER NOT NULL DEFAULT 0,
    ref                 TEXT,            -- branch or tag requested
    commit_sha          TEXT,            -- what was actually assessed
    -- Hash of the serialized evidence document. Two assessments with the same hash saw the same
    -- facts, which makes their differing conclusions a question about the model, not the code.
    evidence_hash       TEXT,
    -- Version of standards/ used. A pillar definition change alters every future judgement, so an
    -- old assessment must record which baseline it was judged against.
    standards_version   TEXT,
    -- SA-supplied context: what the tool is for, who depends on it. Answers materially change the
    -- judgement, which is why they are recorded rather than merely used.
    intake_json         TEXT,
    created_at          TEXT NOT NULL,
    started_at          TEXT,
    finished_at         TEXT,
    created_by          TEXT NOT NULL
);

CREATE INDEX idx_assessments_repo ON assessments(repository_id, created_at DESC);
CREATE INDEX idx_assessments_status ON assessments(status) WHERE status NOT IN ('complete', 'failed', 'cancelled');

-- One row per reasoning pass, written BEFORE the next pass begins. This is what makes a run
-- resumable: an outage between passes resumes from here rather than restarting the pipeline and
-- paying for every completed pass again.
CREATE TABLE passes (
    id              TEXT PRIMARY KEY,
    assessment_id   TEXT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    -- Stable name, registered in backend/factory/passes.py. This is a database value, so renaming
    -- a pass is a migration rather than a refactor.
    pass_name       TEXT NOT NULL,
    status          TEXT NOT NULL,       -- pending | running | complete | failed
    output_json     TEXT,
    error           TEXT,
    started_at      TEXT,
    finished_at     TEXT,
    UNIQUE (assessment_id, pass_name)
);

-- The provenance record. One row per call to the model, kept whether the call succeeded or not.
CREATE TABLE llm_calls (
    id                  TEXT PRIMARY KEY,
    assessment_id       TEXT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    pass_name           TEXT NOT NULL,
    model               TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    temperature         REAL NOT NULL,
    evidence_hash       TEXT,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    duration_ms         INTEGER,
    status              TEXT NOT NULL,   -- ok | error | timeout
    error               TEXT,
    -- Full response body. Large, and worth it: see the header note.
    raw_response        TEXT,
    created_at          TEXT NOT NULL
);

CREATE INDEX idx_llm_calls_assessment ON llm_calls(assessment_id, created_at);

CREATE TABLE findings (
    id              TEXT PRIMARY KEY,
    assessment_id   TEXT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    -- Pillar id from standards/pillars/*.md frontmatter.
    pillar_id       TEXT NOT NULL,
    -- Stable identifier for the specific check, e.g. 'D1'. Lets two assessments of the same
    -- repository be diffed by check rather than by prose.
    criterion       TEXT,
    severity        TEXT NOT NULL,       -- blocker | major | minor | info
    title           TEXT NOT NULL,
    detail          TEXT,
    -- Citation. A finding with neither a file nor an explicit reason for having none is not
    -- actionable, and the renderer marks it as such rather than hiding it.
    file_path       TEXT,
    line_start      INTEGER,
    line_end        INTEGER,
    -- scanner | model. The ratchet's core distinction.
    origin          TEXT NOT NULL,
    -- Set when the model raised a scanner finding's severity: the severity it started at.
    escalated_from  TEXT,
    -- Which scanner produced it, for false-positive triage.
    detector        TEXT,
    remediation     TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_findings_assessment ON findings(assessment_id, pillar_id, severity);

-- Rendered documents. Kept on disk under var/artifacts and referenced here, because a 200KB
-- Markdown blob in a row makes every SELECT * expensive for no benefit.
CREATE TABLE artifacts (
    id              TEXT PRIMARY KEY,
    assessment_id   TEXT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,       -- scorecard | remediation_plan | open_questions | agents_md | evidence
    filename        TEXT NOT NULL,
    bytes           INTEGER NOT NULL,
    sha256          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (assessment_id, kind)
);

-- The evidence document itself, stored so an assessment can be re-reasoned without re-cloning.
-- Redacted before it ever gets here: redaction happens in the evidence layer, before serialization.
CREATE TABLE evidence (
    assessment_id   TEXT PRIMARY KEY REFERENCES assessments(id) ON DELETE CASCADE,
    hash            TEXT NOT NULL,
    document_json   TEXT NOT NULL,
    bytes           INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
