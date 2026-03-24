<?php
/**
 * SQLite Database wrapper using PDO
 */
class Database {
    private static ?PDO $instance = null;

    public static function getInstance(): PDO {
        if (self::$instance === null) {
            if (!is_dir(DATA_DIR)) {
                mkdir(DATA_DIR, 0755, true);
            }
            self::$instance = new PDO('sqlite:' . DB_PATH, null, null, [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
                PDO::ATTR_EMULATE_PREPARES => false,
            ]);
            self::$instance->exec('PRAGMA journal_mode=WAL');
            self::$instance->exec('PRAGMA foreign_keys=ON');
            self::$instance->exec('PRAGMA busy_timeout=5000');
        }
        return self::$instance;
    }

    public static function migrate(): void {
        $db = self::getInstance();

        $db->exec("CREATE TABLE IF NOT EXISTS migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            applied_at TEXT DEFAULT (datetime('now'))
        )");

        $applied = $db->query("SELECT name FROM migrations")->fetchAll(PDO::FETCH_COLUMN);
        $migrations = self::getMigrations();

        foreach ($migrations as $name => $sql) {
            if (!in_array($name, $applied)) {
                $db->exec($sql);
                $stmt = $db->prepare("INSERT INTO migrations (name) VALUES (?)");
                $stmt->execute([$name]);
            }
        }
    }

    private static function getMigrations(): array {
        return [
            '001_users' => "
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT DEFAULT 'admin',
                    is_active INTEGER DEFAULT 1,
                    last_login TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
            ",
            '002_contacts' => "
                CREATE TABLE contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    first_name TEXT DEFAULT '',
                    last_name TEXT DEFAULT '',
                    company TEXT DEFAULT '',
                    phone TEXT DEFAULT '',
                    status TEXT DEFAULT 'subscribed',
                    source TEXT DEFAULT 'manual',
                    ip_address TEXT DEFAULT '',
                    lead_score INTEGER DEFAULT 0,
                    custom_fields TEXT DEFAULT '{}',
                    notes TEXT DEFAULT '',
                    unsubscribed_at TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX idx_contacts_email ON contacts(email);
                CREATE INDEX idx_contacts_status ON contacts(status);
                CREATE INDEX idx_contacts_created ON contacts(created_at);
            ",
            '003_tags' => "
                CREATE TABLE tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    color TEXT DEFAULT '#6366f1',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE contact_tags (
                    contact_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (contact_id, tag_id),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
                );
            ",
            '004_lists' => "
                CREATE TABLE lists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    type TEXT DEFAULT 'static',
                    segment_rules TEXT DEFAULT '[]',
                    contact_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE list_contacts (
                    list_id INTEGER NOT NULL,
                    contact_id INTEGER NOT NULL,
                    added_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (list_id, contact_id),
                    FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE,
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                );
            ",
            '005_templates' => "
                CREATE TABLE templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    subject TEXT DEFAULT '',
                    html_content TEXT DEFAULT '',
                    text_content TEXT DEFAULT '',
                    category TEXT DEFAULT 'general',
                    thumbnail TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
            ",
            '006_campaigns' => "
                CREATE TABLE campaigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    subject TEXT DEFAULT '',
                    from_name TEXT DEFAULT '',
                    from_email TEXT DEFAULT '',
                    reply_to TEXT DEFAULT '',
                    template_id INTEGER,
                    list_id INTEGER,
                    html_content TEXT DEFAULT '',
                    text_content TEXT DEFAULT '',
                    status TEXT DEFAULT 'draft',
                    type TEXT DEFAULT 'regular',
                    ab_variant TEXT DEFAULT '',
                    scheduled_at TEXT,
                    sent_at TEXT,
                    completed_at TEXT,
                    total_recipients INTEGER DEFAULT 0,
                    total_sent INTEGER DEFAULT 0,
                    total_delivered INTEGER DEFAULT 0,
                    total_opened INTEGER DEFAULT 0,
                    total_clicked INTEGER DEFAULT 0,
                    total_bounced INTEGER DEFAULT 0,
                    total_unsubscribed INTEGER DEFAULT 0,
                    total_complained INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE SET NULL,
                    FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE SET NULL
                );
                CREATE INDEX idx_campaigns_status ON campaigns(status);
            ",
            '007_email_events' => "
                CREATE TABLE email_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER,
                    automation_id INTEGER,
                    contact_id INTEGER NOT NULL,
                    message_id TEXT DEFAULT '',
                    type TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    ip_address TEXT DEFAULT '',
                    user_agent TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                );
                CREATE INDEX idx_events_campaign ON email_events(campaign_id);
                CREATE INDEX idx_events_contact ON email_events(contact_id);
                CREATE INDEX idx_events_type ON email_events(type);
                CREATE INDEX idx_events_created ON email_events(created_at);
                CREATE INDEX idx_events_message ON email_events(message_id);
            ",
            '008_automations' => "
                CREATE TABLE automations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    trigger_type TEXT NOT NULL,
                    trigger_config TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'draft',
                    total_entered INTEGER DEFAULT 0,
                    total_completed INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE automation_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    automation_id INTEGER NOT NULL,
                    step_order INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    config TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (automation_id) REFERENCES automations(id) ON DELETE CASCADE
                );
                CREATE TABLE automation_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    automation_id INTEGER NOT NULL,
                    step_id INTEGER NOT NULL,
                    contact_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'waiting',
                    execute_at TEXT NOT NULL,
                    executed_at TEXT,
                    result TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (automation_id) REFERENCES automations(id) ON DELETE CASCADE,
                    FOREIGN KEY (step_id) REFERENCES automation_steps(id) ON DELETE CASCADE,
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                );
                CREATE INDEX idx_queue_execute ON automation_queue(execute_at, status);
            ",
            '009_forms' => "
                CREATE TABLE forms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    fields TEXT DEFAULT '[]',
                    settings TEXT DEFAULT '{}',
                    list_id INTEGER,
                    tags_to_apply TEXT DEFAULT '[]',
                    success_message TEXT DEFAULT 'Thank you for subscribing!',
                    redirect_url TEXT DEFAULT '',
                    submit_button_text TEXT DEFAULT 'Subscribe',
                    style TEXT DEFAULT '{}',
                    total_views INTEGER DEFAULT 0,
                    total_submissions INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE SET NULL
                );
                CREATE TABLE form_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    form_id INTEGER NOT NULL,
                    contact_id INTEGER,
                    data TEXT DEFAULT '{}',
                    ip_address TEXT DEFAULT '',
                    user_agent TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (form_id) REFERENCES forms(id) ON DELETE CASCADE,
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL
                );
            ",
            '010_landing_pages' => "
                CREATE TABLE landing_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    html_content TEXT DEFAULT '',
                    css_content TEXT DEFAULT '',
                    form_id INTEGER,
                    meta_title TEXT DEFAULT '',
                    meta_description TEXT DEFAULT '',
                    status TEXT DEFAULT 'draft',
                    total_views INTEGER DEFAULT 0,
                    total_conversions INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (form_id) REFERENCES forms(id) ON DELETE SET NULL
                );
                CREATE INDEX idx_pages_slug ON landing_pages(slug);
            ",
            '011_settings' => "
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT DEFAULT '',
                    updated_at TEXT DEFAULT (datetime('now'))
                );
            ",
            '012_activity_log' => "
                CREATE TABLE activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    ip_address TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX idx_activity_created ON activity_log(created_at);
            ",
            '013_custom_fields_def' => "
                CREATE TABLE custom_field_definitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    label TEXT NOT NULL,
                    type TEXT DEFAULT 'text',
                    options TEXT DEFAULT '[]',
                    is_required INTEGER DEFAULT 0,
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );
            ",
            '014_ab_tests' => "
                CREATE TABLE ab_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER NOT NULL,
                    variant_a_subject TEXT DEFAULT '',
                    variant_b_subject TEXT DEFAULT '',
                    variant_a_content TEXT DEFAULT '',
                    variant_b_content TEXT DEFAULT '',
                    split_percentage INTEGER DEFAULT 50,
                    winner_metric TEXT DEFAULT 'open_rate',
                    winner TEXT DEFAULT '',
                    status TEXT DEFAULT 'running',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
                );
            ",
            '015_default_settings' => "
                INSERT OR IGNORE INTO settings (key, value) VALUES
                    ('site_name', 'MarketFlow'),
                    ('site_url', 'http://localhost:8080'),
                    ('from_email', 'noreply@example.com'),
                    ('from_name', 'MarketFlow'),
                    ('reply_to', ''),
                    ('smtp_host', 'localhost'),
                    ('smtp_port', '25'),
                    ('smtp_encryption', ''),
                    ('smtp_username', ''),
                    ('smtp_password', ''),
                    ('company_name', ''),
                    ('company_address', ''),
                    ('unsubscribe_page', ''),
                    ('double_optin', '0'),
                    ('track_opens', '1'),
                    ('track_clicks', '1'),
                    ('bounce_handling', '1'),
                    ('sending_rate_limit', '100'),
                    ('sending_rate_period', '3600');
            ",
            '016_default_admin' => "
                INSERT OR IGNORE INTO users (email, password_hash, name, role) VALUES
                    ('admin@example.com', '', 'Administrator', 'admin');
            ",
        ];
    }
}
