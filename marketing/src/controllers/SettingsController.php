<?php
class SettingsController {
    public static function index(): void {
        $db = Database::getInstance();
        $rows = $db->query("SELECT key, value FROM settings")->fetchAll();
        $settings = [];
        foreach ($rows as $row) {
            // Mask password
            if ($row['key'] === 'smtp_password' && $row['value']) {
                $settings[$row['key']] = '********';
            } else {
                $settings[$row['key']] = $row['value'];
            }
        }
        Router::json($settings);
    }

    public static function update(): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        $allowedKeys = [
            'site_name', 'site_url', 'from_email', 'from_name', 'reply_to',
            'smtp_host', 'smtp_port', 'smtp_encryption', 'smtp_username', 'smtp_password',
            'company_name', 'company_address', 'unsubscribe_page',
            'double_optin', 'track_opens', 'track_clicks', 'bounce_handling',
            'sending_rate_limit', 'sending_rate_period',
        ];

        foreach ($data as $key => $value) {
            if (!in_array($key, $allowedKeys)) continue;
            // Don't overwrite password with mask
            if ($key === 'smtp_password' && $value === '********') continue;

            $db->prepare("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))")
                ->execute([$key, $value]);
        }

        ActivityLog::log('settings_updated', 'Settings updated');
        Router::json(['message' => 'Settings updated']);
    }

    public static function testSmtp(): void {
        $data = Router::getBody();
        $config = [
            'host' => $data['smtp_host'] ?? '',
            'port' => $data['smtp_port'] ?? 25,
            'encryption' => $data['smtp_encryption'] ?? '',
            'username' => $data['smtp_username'] ?? '',
            'password' => $data['smtp_password'] ?? '',
        ];

        // If password is masked, get real one
        if ($config['password'] === '********') {
            $db = Database::getInstance();
            $stmt = $db->prepare("SELECT value FROM settings WHERE key = 'smtp_password'");
            $stmt->execute();
            $row = $stmt->fetch();
            $config['password'] = $row['value'] ?? '';
        }

        $mailer = new Mailer($config);
        $result = $mailer->testConnection();
        Router::json($result);
    }

    public static function sendTestEmail(): void {
        $data = Router::getBody();
        $email = $data['email'] ?? '';
        if (!$email || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
            Router::json(['error' => 'Valid email required'], 422);
            return;
        }

        $mailer = new Mailer();
        $result = $mailer->send(
            $email,
            'Test Email from ' . APP_NAME,
            '<h2>Test Email</h2><p>If you received this email, your SMTP configuration is working correctly!</p><p>Sent at: ' . date('Y-m-d H:i:s') . '</p>'
        );

        Router::json($result);
    }

    // Tag management
    public static function listTags(): void {
        $db = Database::getInstance();
        $tags = $db->query("SELECT t.*, COUNT(ct.contact_id) as contact_count FROM tags t LEFT JOIN contact_tags ct ON t.id = ct.tag_id GROUP BY t.id ORDER BY t.name")->fetchAll();
        Router::json($tags);
    }

    public static function createTag(): void {
        $db = Database::getInstance();
        $data = Router::getBody();
        if (empty($data['name'])) { Router::json(['error' => 'Name is required'], 422); return; }

        $db->prepare("INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)")
            ->execute([$data['name'], $data['color'] ?? '#6366f1']);

        Router::json(['message' => 'Tag created'], 201);
    }

    public static function updateTag(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();
        $fields = [];
        $values = [];
        if (isset($data['name'])) { $fields[] = "name = ?"; $values[] = $data['name']; }
        if (isset($data['color'])) { $fields[] = "color = ?"; $values[] = $data['color']; }
        if ($fields) {
            $values[] = $params['id'];
            $db->prepare("UPDATE tags SET " . implode(', ', $fields) . " WHERE id = ?")->execute($values);
        }
        Router::json(['message' => 'Tag updated']);
    }

    public static function deleteTag(array $params): void {
        $db = Database::getInstance();
        $db->prepare("DELETE FROM tags WHERE id = ?")->execute([$params['id']]);
        Router::json(['message' => 'Tag deleted']);
    }

    // Custom field management
    public static function listCustomFields(): void {
        $db = Database::getInstance();
        $fields = $db->query("SELECT * FROM custom_field_definitions ORDER BY sort_order")->fetchAll();
        foreach ($fields as &$f) $f['options'] = json_decode($f['options'], true);
        Router::json($fields);
    }

    public static function createCustomField(): void {
        $db = Database::getInstance();
        $data = Router::getBody();
        if (empty($data['name']) || empty($data['label'])) {
            Router::json(['error' => 'Name and label are required'], 422);
            return;
        }

        $name = preg_replace('/[^a-z0-9_]/', '_', strtolower($data['name']));
        $db->prepare("INSERT INTO custom_field_definitions (name, label, type, options, is_required, sort_order) VALUES (?, ?, ?, ?, ?, ?)")
            ->execute([$name, $data['label'], $data['type'] ?? 'text', json_encode($data['options'] ?? []), $data['is_required'] ?? 0, $data['sort_order'] ?? 0]);

        Router::json(['message' => 'Custom field created'], 201);
    }

    public static function deleteCustomField(array $params): void {
        $db = Database::getInstance();
        $db->prepare("DELETE FROM custom_field_definitions WHERE id = ?")->execute([$params['id']]);
        Router::json(['message' => 'Custom field deleted']);
    }

    // User management
    public static function listUsers(): void {
        $db = Database::getInstance();
        $users = $db->query("SELECT id, email, name, role, is_active, last_login, created_at FROM users ORDER BY created_at")->fetchAll();
        Router::json($users);
    }

    public static function createUser(): void {
        $db = Database::getInstance();
        $data = Router::getBody();
        if (empty($data['email']) || empty($data['name'])) {
            Router::json(['error' => 'Email and name required'], 422);
            return;
        }

        $hash = !empty($data['password']) ? password_hash($data['password'], PASSWORD_BCRYPT) : '';
        $db->prepare("INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)")
            ->execute([$data['email'], $hash, $data['name'], $data['role'] ?? 'admin']);

        Router::json(['message' => 'User created'], 201);
    }

    public static function updateProfile(): void {
        $data = Router::getBody();
        $userId = Auth::userId();
        $db = Database::getInstance();

        if (!empty($data['name'])) {
            $db->prepare("UPDATE users SET name = ?, updated_at = datetime('now') WHERE id = ?")->execute([$data['name'], $userId]);
            $_SESSION['user_name'] = $data['name'];
        }

        if (!empty($data['current_password']) && !empty($data['new_password'])) {
            $stmt = $db->prepare("SELECT password_hash FROM users WHERE id = ?");
            $stmt->execute([$userId]);
            $user = $stmt->fetch();

            if (!password_verify($data['current_password'], $user['password_hash'])) {
                Router::json(['error' => 'Current password is incorrect'], 422);
                return;
            }
            Auth::changePassword($userId, $data['new_password']);
        }

        Router::json(['message' => 'Profile updated']);
    }
}
