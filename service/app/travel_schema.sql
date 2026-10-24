PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS organizations (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, organization_type TEXT NOT NULL,
 region TEXT NOT NULL, personnel_type TEXT NOT NULL, rule_packs TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_packs (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, layer TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS travel_rules (
 id TEXT PRIMARY KEY, pack_id TEXT NOT NULL REFERENCES rule_packs(id), title TEXT NOT NULL,
 article TEXT NOT NULL, text TEXT NOT NULL, effective_date TEXT NOT NULL, expiry_date TEXT,
 version TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('synthetic','unverified')),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_travel_rules_scope ON travel_rules(pack_id,effective_date,expiry_date);
CREATE TABLE IF NOT EXISTS travel_cases (
 id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
 profile_snapshot TEXT NOT NULL, trip_json TEXT NOT NULL, rule_snapshot TEXT NOT NULL,
 parse_issues TEXT NOT NULL DEFAULT '[]', version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS travel_transactions (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES travel_cases(id) ON DELETE CASCADE,
 transaction_date TEXT NOT NULL, transaction_time TEXT NOT NULL, merchant TEXT NOT NULL,
 amount INTEGER NOT NULL CHECK(amount > 0), category TEXT NOT NULL,
 source_type TEXT NOT NULL, fingerprint TEXT NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0,
 decision TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '',
 UNIQUE(case_id,fingerprint)
);
CREATE INDEX IF NOT EXISTS ix_travel_transactions_case ON travel_transactions(case_id);
CREATE TABLE IF NOT EXISTS travel_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL REFERENCES travel_cases(id),
 event_type TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS travel_drafts (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES travel_cases(id), case_version INTEGER NOT NULL,
 snapshot TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS travel_case_legalpacks (
 case_id TEXT PRIMARY KEY REFERENCES travel_cases(id), snapshot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS travel_calculations (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES travel_cases(id),
 case_version INTEGER NOT NULL, inputs_json TEXT NOT NULL,
 result_json TEXT NOT NULL, rulepack_snapshot TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_travel_calculations_case ON travel_calculations(case_id,case_version);
CREATE TABLE IF NOT EXISTS travel_documents (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES travel_cases(id),
 filename TEXT NOT NULL, media_type TEXT NOT NULL, sha256 TEXT NOT NULL,
 original BLOB NOT NULL, extraction TEXT NOT NULL, suggested_text TEXT NOT NULL,
 confirmed_text TEXT, confirmation_reason TEXT, created_at TEXT NOT NULL, confirmed_at TEXT,
 UNIQUE(case_id,sha256)
);
CREATE INDEX IF NOT EXISTS ix_travel_documents_case ON travel_documents(case_id);
CREATE TABLE IF NOT EXISTS travel_document_transactions (
 document_id TEXT NOT NULL REFERENCES travel_documents(id),
 transaction_id TEXT NOT NULL REFERENCES travel_transactions(id),
 PRIMARY KEY(document_id,transaction_id)
);
CREATE TABLE IF NOT EXISTS travel_case_workflow (
 case_id TEXT PRIMARY KEY REFERENCES travel_cases(id), revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS travel_tasks (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES travel_cases(id),
 title TEXT NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('open','done')),
 resolution TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_travel_tasks_case ON travel_tasks(case_id,status);
CREATE TABLE IF NOT EXISTS travel_case_origins (
 case_id TEXT PRIMARY KEY REFERENCES travel_cases(id), scenario_id TEXT NOT NULL,
 expected_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_travel_origins_scenario ON travel_case_origins(scenario_id,created_at);
CREATE TABLE IF NOT EXISTS travel_organization_settings (
 organization_id TEXT PRIMARY KEY REFERENCES organizations(id), revision INTEGER NOT NULL,
 settings_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS travel_rule_sources (
 id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
 metadata_json TEXT NOT NULL, original BLOB NOT NULL, sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(organization_id,sha256)
);
CREATE TABLE IF NOT EXISTS travel_rule_reviews (
 id TEXT PRIMARY KEY, rule_id TEXT NOT NULL REFERENCES travel_rules(id),
 revision INTEGER NOT NULL, source_id TEXT NOT NULL REFERENCES travel_rule_sources(id),
 review_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(rule_id,revision)
);
CREATE TABLE IF NOT EXISTS travel_form_templates (
 id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
 name TEXT NOT NULL, version TEXT NOT NULL, effective_date TEXT NOT NULL, expiry_date TEXT,
 filename TEXT NOT NULL, original BLOB NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(organization_id,name,version)
);
CREATE TABLE IF NOT EXISTS travel_stage_notes (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES travel_cases(id),
 stage TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
 case_version INTEGER NOT NULL, context_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_travel_stage_notes_case ON travel_stage_notes(case_id,created_at);
CREATE TABLE IF NOT EXISTS travel_stage_note_tasks (
 note_id TEXT PRIMARY KEY REFERENCES travel_stage_notes(id),
 task_id TEXT NOT NULL UNIQUE REFERENCES travel_tasks(id), created_at TEXT NOT NULL
);
