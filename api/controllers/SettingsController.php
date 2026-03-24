<?php
class SettingsController {
    public static function index(): void {
        $db = Database::getInstance();
        $rows = $db->query("SELECT key, value FROM settings")->fetchAll();
        $settings = [];
        foreach ($rows as $r) {
            // Mask sensitive values
            if (str_contains($r['key'], 'password') || str_contains($r['key'], 'secret')) {
                $settings[$r['key']] = $r['value'] ? '********' : '';
            } elseif (str_contains($r['key'], 'api_key') || str_contains($r['key'], 'access_token')) {
                $settings[$r['key']] = $r['value'] ? substr($r['value'], 0, 8) . '...' : '';
            } else {
                $settings[$r['key']] = $r['value'];
            }
        }
        Router::json($settings);
    }

    /** Get raw settings (internal use, not exposed to API directly) */
    public static function raw(): array {
        $db = Database::getInstance();
        $rows = $db->query("SELECT key, value FROM settings")->fetchAll();
        $s = [];
        foreach ($rows as $r) $s[$r['key']] = $r['value'];
        return $s;
    }

    public static function update(): void {
        $db = Database::getInstance(); $d = Router::body();

        $allowed = [
            'site_name','site_url','from_email','from_name','reply_to',
            'smtp_host','smtp_port','smtp_encryption','smtp_username','smtp_password',
            'meta_access_token','fb_page_id','ig_user_id',
            'tiktok_access_token','tiktok_open_id',
            'claude_api_key','openai_api_key','gemini_api_key',
            'default_text_model','default_image_model',
            'company_name','company_address',
            'track_opens','track_clicks',
            'twitter_api_key','twitter_api_secret','twitter_access_token','twitter_access_secret',
            'linkedin_access_token','pinterest_access_token',
        ];

        foreach ($d as $k => $v) {
            if (!in_array($k, $allowed)) continue;
            // Don't overwrite masked values
            if ($v === '********' || (is_string($v) && str_ends_with($v, '...'))) continue;
            $db->prepare("INSERT OR REPLACE INTO settings (key,value,updated_at) VALUES (?,?,datetime('now'))")
                ->execute([$k, $v]);
        }
        logActivity('settings_updated', 'Settings updated');
        Router::json(['message' => 'Settings updated']);
    }

    public static function testSmtp(): void {
        $mailer = new Mailer();
        Router::json($mailer->testConnection());
    }

    public static function testEmail(): void {
        $d = Router::body(); $email = $d['email'] ?? '';
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) { Router::json(['error' => 'Valid email required'], 422); return; }
        $mailer = new Mailer();
        Router::json($mailer->send($email, 'Test Email from '.APP_NAME, '<h2>Test Email</h2><p>SMTP is working! Sent at '.date('Y-m-d H:i:s').'</p>'));
    }

    // Tags
    public static function tags(): void {
        $db = Database::getInstance();
        Router::json($db->query("SELECT t.*,COUNT(ct.contact_id) as contact_count FROM tags t LEFT JOIN contact_tags ct ON t.id=ct.tag_id GROUP BY t.id ORDER BY t.name")->fetchAll());
    }
    public static function createTag(): void {
        $d = Router::body();
        if (empty($d['name'])) { Router::json(['error' => 'Name required'], 422); return; }
        Database::getInstance()->prepare("INSERT OR IGNORE INTO tags (name,color) VALUES (?,?)")->execute([$d['name'],$d['color']??'#FF6B35']);
        Router::json(['message' => 'Tag created'], 201);
    }
    public static function updateTag(array $p): void {
        $d = Router::body(); $f = []; $v = [];
        if (isset($d['name'])) { $f[] = "name=?"; $v[] = $d['name']; }
        if (isset($d['color'])) { $f[] = "color=?"; $v[] = $d['color']; }
        if ($f) { $v[] = $p['id']; Database::getInstance()->prepare("UPDATE tags SET ".implode(',',$f)." WHERE id=?")->execute($v); }
        Router::json(['message' => 'Updated']);
    }
    public static function deleteTag(array $p): void {
        Database::getInstance()->prepare("DELETE FROM tags WHERE id=?")->execute([$p['id']]);
        Router::json(['message' => 'Deleted']);
    }

    // Users
    public static function users(): void {
        Router::json(Database::getInstance()->query("SELECT id,email,name,role,is_active,last_login,created_at FROM users ORDER BY created_at")->fetchAll());
    }
    public static function createUser(): void {
        $d = Router::body();
        if (empty($d['email']) || empty($d['name'])) { Router::json(['error' => 'Email and name required'], 422); return; }
        $hash = !empty($d['password']) ? password_hash($d['password'], PASSWORD_BCRYPT) : '';
        Database::getInstance()->prepare("INSERT INTO users (email,password_hash,name,role) VALUES (?,?,?,?)")
            ->execute([$d['email'],$hash,$d['name'],$d['role']??'admin']);
        Router::json(['message' => 'User created'], 201);
    }
    public static function updateProfile(): void {
        $d = Router::body(); $uid = $_SESSION['user_id'] ?? 0; $db = Database::getInstance();
        if (!empty($d['name'])) { $db->prepare("UPDATE users SET name=? WHERE id=?")->execute([$d['name'],$uid]); $_SESSION['user_name'] = $d['name']; }
        if (!empty($d['current_password']) && !empty($d['new_password'])) {
            $stmt = $db->prepare("SELECT password_hash FROM users WHERE id=?"); $stmt->execute([$uid]); $u = $stmt->fetch();
            if (!password_verify($d['current_password'], $u['password_hash'])) { Router::json(['error' => 'Wrong password'], 422); return; }
            $db->prepare("UPDATE users SET password_hash=? WHERE id=?")->execute([password_hash($d['new_password'], PASSWORD_BCRYPT),$uid]);
        }
        Router::json(['message' => 'Profile updated']);
    }
}
