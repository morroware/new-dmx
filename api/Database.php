<?php
class Database {
    private static ?PDO $instance = null;

    public static function getInstance(): PDO {
        if (self::$instance === null) {
            if (!is_dir(DATA_DIR)) mkdir(DATA_DIR, 0755, true);
            self::$instance = new PDO('sqlite:' . DB_PATH, null, null, [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            ]);
            self::$instance->exec('PRAGMA journal_mode=WAL');
            self::$instance->exec('PRAGMA foreign_keys=ON');
        }
        return self::$instance;
    }

    public static function migrate(): void {
        $db = self::getInstance();
        $db->exec("CREATE TABLE IF NOT EXISTS migrations (
            id INTEGER PRIMARY KEY, name TEXT UNIQUE, applied_at TEXT DEFAULT (datetime('now'))
        )");
        $applied = $db->query("SELECT name FROM migrations")->fetchAll(PDO::FETCH_COLUMN);

        foreach (self::getMigrations() as $name => $sql) {
            if (!in_array($name, $applied)) {
                $db->exec($sql);
                $db->prepare("INSERT INTO migrations (name) VALUES (?)")->execute([$name]);
            }
        }
    }

    private static function getMigrations(): array {
        return [
            '001_settings' => "
                CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT DEFAULT '', updated_at TEXT DEFAULT (datetime('now')));
                INSERT INTO settings (key, value) VALUES
                    ('site_name','NEXUS'),('site_url','http://localhost:8080'),
                    ('meta_access_token',''),('fb_page_id',''),('ig_user_id',''),
                    ('tiktok_access_token',''),('tiktok_open_id',''),
                    ('claude_api_key',''),('openai_api_key',''),('gemini_api_key',''),
                    ('default_text_model','claude'),('default_image_model','gemini-free'),
                    ('smtp_host',''),('smtp_port','587'),('smtp_encryption','tls'),
                    ('smtp_username',''),('smtp_password',''),
                    ('from_email',''),('from_name','NEXUS'),('reply_to',''),
                    ('company_name',''),('company_address',''),
                    ('track_opens','1'),('track_clicks','1'),
                    ('twitter_api_key',''),('twitter_api_secret',''),
                    ('twitter_access_token',''),('twitter_access_secret',''),
                    ('linkedin_access_token',''),
                    ('pinterest_access_token','');
            ",
            '002_users' => "
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
                    password_hash TEXT DEFAULT '', name TEXT NOT NULL, role TEXT DEFAULT 'admin',
                    is_active INTEGER DEFAULT 1, last_login TEXT,
                    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
                );
                INSERT INTO users (email, name, role) VALUES ('admin@nexus.local', 'Admin', 'admin');
            ",
            '003_contacts' => "
                CREATE TABLE contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
                    first_name TEXT DEFAULT '', last_name TEXT DEFAULT '', company TEXT DEFAULT '',
                    phone TEXT DEFAULT '', status TEXT DEFAULT 'subscribed', source TEXT DEFAULT 'manual',
                    lead_score INTEGER DEFAULT 0, custom_fields TEXT DEFAULT '{}', notes TEXT DEFAULT '',
                    ip_address TEXT DEFAULT '', unsubscribed_at TEXT,
                    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX idx_contacts_email ON contacts(email);
                CREATE INDEX idx_contacts_status ON contacts(status);
            ",
            '004_tags' => "
                CREATE TABLE tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
                    color TEXT DEFAULT '#FF6B35', created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE contact_tags (
                    contact_id INTEGER, tag_id INTEGER,
                    PRIMARY KEY (contact_id, tag_id),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
                );
            ",
            '005_lists' => "
                CREATE TABLE lists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    description TEXT DEFAULT '', type TEXT DEFAULT 'static',
                    segment_rules TEXT DEFAULT '[]', contact_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE list_contacts (
                    list_id INTEGER, contact_id INTEGER, added_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (list_id, contact_id),
                    FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE,
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                );
            ",
            '006_templates' => "
                CREATE TABLE templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    subject TEXT DEFAULT '', html_content TEXT DEFAULT '', text_content TEXT DEFAULT '',
                    category TEXT DEFAULT 'general', is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
                );
            ",
            '007_campaigns' => "
                CREATE TABLE campaigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    type TEXT DEFAULT 'email', subject TEXT DEFAULT '',
                    from_name TEXT DEFAULT '', from_email TEXT DEFAULT '', reply_to TEXT DEFAULT '',
                    template_id INTEGER, list_id INTEGER,
                    html_content TEXT DEFAULT '', text_content TEXT DEFAULT '',
                    status TEXT DEFAULT 'draft', scheduled_at TEXT,
                    sent_at TEXT, completed_at TEXT,
                    total_recipients INTEGER DEFAULT 0, total_sent INTEGER DEFAULT 0,
                    total_delivered INTEGER DEFAULT 0, total_opened INTEGER DEFAULT 0,
                    total_clicked INTEGER DEFAULT 0, total_bounced INTEGER DEFAULT 0,
                    total_unsubscribed INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE SET NULL,
                    FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE SET NULL
                );
            ",
            '008_email_events' => "
                CREATE TABLE email_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER,
                    contact_id INTEGER, message_id TEXT DEFAULT '', type TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}', ip_address TEXT DEFAULT '', user_agent TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                );
                CREATE INDEX idx_events_campaign ON email_events(campaign_id);
                CREATE INDEX idx_events_type ON email_events(type);
            ",
            '009_social_posts' => "
                CREATE TABLE social_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT DEFAULT '',
                    platforms TEXT DEFAULT '[]', media_urls TEXT DEFAULT '[]',
                    ai_model TEXT DEFAULT '', ai_prompt TEXT DEFAULT '',
                    content_type TEXT DEFAULT 'social_post', tone TEXT DEFAULT 'professional',
                    status TEXT DEFAULT 'draft', scheduled_at TEXT,
                    results TEXT DEFAULT '[]', published_at TEXT,
                    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX idx_social_status ON social_posts(status);
            ",
            '010_social_accounts' => "
                CREATE TABLE social_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL,
                    account_name TEXT DEFAULT '', account_id TEXT DEFAULT '',
                    access_token TEXT DEFAULT '', refresh_token TEXT DEFAULT '',
                    token_expires_at TEXT, metadata TEXT DEFAULT '{}',
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
                );
            ",
            '011_automations' => "
                CREATE TABLE automations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    description TEXT DEFAULT '', trigger_type TEXT NOT NULL,
                    trigger_config TEXT DEFAULT '{}', status TEXT DEFAULT 'draft',
                    total_entered INTEGER DEFAULT 0, total_completed INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE automation_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, automation_id INTEGER NOT NULL,
                    step_order INTEGER NOT NULL, type TEXT NOT NULL, config TEXT DEFAULT '{}',
                    FOREIGN KEY (automation_id) REFERENCES automations(id) ON DELETE CASCADE
                );
                CREATE TABLE automation_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, automation_id INTEGER NOT NULL,
                    step_id INTEGER NOT NULL, contact_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'waiting', execute_at TEXT NOT NULL,
                    executed_at TEXT, result TEXT DEFAULT '',
                    FOREIGN KEY (automation_id) REFERENCES automations(id) ON DELETE CASCADE
                );
            ",
            '012_forms' => "
                CREATE TABLE forms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    description TEXT DEFAULT '', fields TEXT DEFAULT '[]',
                    settings TEXT DEFAULT '{}', list_id INTEGER, tags_to_apply TEXT DEFAULT '[]',
                    success_message TEXT DEFAULT 'Thank you!', redirect_url TEXT DEFAULT '',
                    submit_button_text TEXT DEFAULT 'Subscribe', style TEXT DEFAULT '{}',
                    total_views INTEGER DEFAULT 0, total_submissions INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE form_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, form_id INTEGER NOT NULL,
                    contact_id INTEGER, data TEXT DEFAULT '{}', ip_address TEXT DEFAULT '',
                    user_agent TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (form_id) REFERENCES forms(id) ON DELETE CASCADE
                );
            ",
            '013_landing_pages' => "
                CREATE TABLE landing_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
                    html_content TEXT DEFAULT '', css_content TEXT DEFAULT '', form_id INTEGER,
                    meta_title TEXT DEFAULT '', meta_description TEXT DEFAULT '',
                    status TEXT DEFAULT 'draft', total_views INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
                );
            ",
            '014_activity_log' => "
                CREATE TABLE activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                    type TEXT NOT NULL, description TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}', created_at TEXT DEFAULT (datetime('now'))
                );
            ",
            '015_content_calendar' => "
                CREATE TABLE calendar_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    description TEXT DEFAULT '', type TEXT DEFAULT 'post',
                    ref_id INTEGER, ref_type TEXT DEFAULT '',
                    start_date TEXT NOT NULL, end_date TEXT,
                    color TEXT DEFAULT '#FF6B35', all_day INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'planned',
                    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
                );
            ",
            '016_media_library' => "
                CREATE TABLE media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL,
                    original_name TEXT DEFAULT '', mime_type TEXT DEFAULT '',
                    size INTEGER DEFAULT 0, url TEXT DEFAULT '',
                    alt_text TEXT DEFAULT '', folder TEXT DEFAULT 'general',
                    ai_generated INTEGER DEFAULT 0, ai_prompt TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
            ",
        ];
    }
}
