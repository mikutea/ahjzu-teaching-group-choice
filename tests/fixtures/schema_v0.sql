CREATE TABLE settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    activity_title TEXT NOT NULL,
    organization_name TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('closed', 'open')),
    public_base_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE majors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE teaching_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    total_capacity INTEGER NOT NULL DEFAULT 30 CHECK (total_capacity >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE quotas (
    major_id INTEGER NOT NULL REFERENCES majors(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES teaching_groups(id) ON DELETE CASCADE,
    capacity INTEGER NOT NULL DEFAULT 0 CHECK (capacity >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (major_id, group_id)
);
CREATE TABLE students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_no TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    major_id INTEGER NOT NULL REFERENCES majors(id) ON DELETE RESTRICT,
    activation_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE selections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
    group_id INTEGER NOT NULL REFERENCES teaching_groups(id) ON DELETE RESTRICT,
    selected_at TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('student', 'admin')),
    operator TEXT NOT NULL,
    revoked_at TEXT,
    revoked_by TEXT
);
CREATE UNIQUE INDEX one_active_selection_per_student
ON selections(student_id) WHERE revoked_at IS NULL;
CREATE INDEX selections_active_group ON selections(group_id, revoked_at);
CREATE INDEX students_major ON students(major_id, active);
CREATE TABLE admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('student', 'admin')),
    subject_id INTEGER NOT NULL,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX sessions_expiry ON sessions(expires_at);
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    details_json TEXT NOT NULL
);
CREATE INDEX audit_logs_time ON audit_logs(occurred_at DESC);
