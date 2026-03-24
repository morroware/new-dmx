<?php
class AutomationController {
    public static function index(): void {
        $db = Database::getInstance();
        $result = Router::paginate($db, "SELECT * FROM automations ORDER BY created_at DESC", [], (int)($_GET['page'] ?? 1));
        Router::json($result);
    }

    public static function show(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM automations WHERE id = ?");
        $stmt->execute([$params['id']]);
        $automation = $stmt->fetch();
        if (!$automation) { Router::json(['error' => 'Not found'], 404); return; }

        $automation['trigger_config'] = json_decode($automation['trigger_config'], true);

        $stmt = $db->prepare("SELECT * FROM automation_steps WHERE automation_id = ? ORDER BY step_order");
        $stmt->execute([$params['id']]);
        $automation['steps'] = $stmt->fetchAll();
        foreach ($automation['steps'] as &$step) {
            $step['config'] = json_decode($step['config'], true);
        }

        // Queue stats
        $stmt = $db->prepare("SELECT status, COUNT(*) as count FROM automation_queue WHERE automation_id = ? GROUP BY status");
        $stmt->execute([$params['id']]);
        $automation['queue_stats'] = [];
        foreach ($stmt->fetchAll() as $row) $automation['queue_stats'][$row['status']] = (int)$row['count'];

        Router::json($automation);
    }

    public static function store(): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        if (empty($data['name'])) { Router::json(['error' => 'Name is required'], 422); return; }
        if (empty($data['trigger_type'])) { Router::json(['error' => 'Trigger type is required'], 422); return; }

        $stmt = $db->prepare("INSERT INTO automations (name, description, trigger_type, trigger_config) VALUES (?, ?, ?, ?)");
        $stmt->execute([
            $data['name'],
            $data['description'] ?? '',
            $data['trigger_type'],
            json_encode($data['trigger_config'] ?? []),
        ]);

        $automationId = $db->lastInsertId();

        // Insert steps
        if (!empty($data['steps'])) {
            foreach ($data['steps'] as $i => $step) {
                $db->prepare("INSERT INTO automation_steps (automation_id, step_order, type, config) VALUES (?, ?, ?, ?)")
                    ->execute([$automationId, $i + 1, $step['type'], json_encode($step['config'] ?? [])]);
            }
        }

        ActivityLog::log('automation_created', "Automation created: {$data['name']}", ['automation_id' => $automationId]);
        Router::json(['id' => $automationId, 'message' => 'Automation created'], 201);
    }

    public static function update(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        $fields = [];
        $values = [];

        foreach (['name', 'description', 'trigger_type', 'status'] as $f) {
            if (isset($data[$f])) { $fields[] = "{$f} = ?"; $values[] = $data[$f]; }
        }
        if (isset($data['trigger_config'])) {
            $fields[] = "trigger_config = ?";
            $values[] = json_encode($data['trigger_config']);
        }

        if ($fields) {
            $fields[] = "updated_at = datetime('now')";
            $values[] = $params['id'];
            $db->prepare("UPDATE automations SET " . implode(', ', $fields) . " WHERE id = ?")->execute($values);
        }

        // Replace steps if provided
        if (isset($data['steps'])) {
            $db->prepare("DELETE FROM automation_steps WHERE automation_id = ?")->execute([$params['id']]);
            foreach ($data['steps'] as $i => $step) {
                $db->prepare("INSERT INTO automation_steps (automation_id, step_order, type, config) VALUES (?, ?, ?, ?)")
                    ->execute([$params['id'], $i + 1, $step['type'], json_encode($step['config'] ?? [])]);
            }
        }

        Router::json(['message' => 'Automation updated']);
    }

    public static function destroy(array $params): void {
        $db = Database::getInstance();
        $db->prepare("DELETE FROM automations WHERE id = ?")->execute([$params['id']]);
        Router::json(['message' => 'Automation deleted']);
    }

    public static function activate(array $params): void {
        $db = Database::getInstance();
        $db->prepare("UPDATE automations SET status = 'active', updated_at = datetime('now') WHERE id = ?")->execute([$params['id']]);
        Router::json(['message' => 'Automation activated']);
    }

    public static function pause(array $params): void {
        $db = Database::getInstance();
        $db->prepare("UPDATE automations SET status = 'paused', updated_at = datetime('now') WHERE id = ?")->execute([$params['id']]);
        Router::json(['message' => 'Automation paused']);
    }

    /**
     * Process automation queue - called by cron or manually
     */
    public static function processQueue(): void {
        $db = Database::getInstance();
        $now = date('Y-m-d H:i:s');

        $stmt = $db->prepare("
            SELECT aq.*, a.status as automation_status, ast.type as step_type, ast.config as step_config
            FROM automation_queue aq
            JOIN automations a ON aq.automation_id = a.id
            JOIN automation_steps ast ON aq.step_id = ast.id
            WHERE aq.status = 'waiting' AND aq.execute_at <= ? AND a.status = 'active'
            ORDER BY aq.execute_at
            LIMIT 50
        ");
        $stmt->execute([$now]);
        $items = $stmt->fetchAll();

        $processed = 0;
        foreach ($items as $item) {
            $config = json_decode($item['step_config'], true);

            switch ($item['step_type']) {
                case 'send_email':
                    self::processEmailStep($item, $config);
                    break;
                case 'add_tag':
                    self::processTagStep($item, $config);
                    break;
                case 'remove_tag':
                    self::processRemoveTagStep($item, $config);
                    break;
                case 'update_field':
                    self::processFieldStep($item, $config);
                    break;
                case 'add_to_list':
                    self::processListStep($item, $config);
                    break;
                case 'update_lead_score':
                    self::processLeadScoreStep($item, $config);
                    break;
                case 'webhook':
                    self::processWebhookStep($item, $config);
                    break;
            }

            // Mark as executed
            $db->prepare("UPDATE automation_queue SET status = 'executed', executed_at = datetime('now') WHERE id = ?")->execute([$item['id']]);

            // Queue next step
            self::queueNextStep($item);
            $processed++;
        }

        Router::json(['processed' => $processed]);
    }

    /**
     * Trigger automation for a contact
     */
    public static function triggerForContact(string $triggerType, int $contactId, array $triggerData = []): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM automations WHERE trigger_type = ? AND status = 'active'");
        $stmt->execute([$triggerType]);
        $automations = $stmt->fetchAll();

        foreach ($automations as $automation) {
            $config = json_decode($automation['trigger_config'], true);

            // Check trigger conditions
            if (!self::checkTriggerConditions($config, $triggerData)) continue;

            // Check if contact already in this automation
            $stmt = $db->prepare("SELECT id FROM automation_queue WHERE automation_id = ? AND contact_id = ? AND status = 'waiting'");
            $stmt->execute([$automation['id'], $contactId]);
            if ($stmt->fetch()) continue;

            // Get first step
            $stmt = $db->prepare("SELECT * FROM automation_steps WHERE automation_id = ? ORDER BY step_order LIMIT 1");
            $stmt->execute([$automation['id']]);
            $firstStep = $stmt->fetch();

            if ($firstStep) {
                $stepConfig = json_decode($firstStep['config'], true);
                $delay = self::calculateDelay($stepConfig);

                $db->prepare("INSERT INTO automation_queue (automation_id, step_id, contact_id, execute_at) VALUES (?, ?, ?, datetime('now', ?))")
                    ->execute([$automation['id'], $firstStep['id'], $contactId, "+{$delay} seconds"]);

                $db->prepare("UPDATE automations SET total_entered = total_entered + 1, updated_at = datetime('now') WHERE id = ?")
                    ->execute([$automation['id']]);
            }
        }
    }

    private static function processEmailStep(array $item, array $config): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM contacts WHERE id = ?");
        $stmt->execute([$item['contact_id']]);
        $contact = $stmt->fetch();
        if (!$contact || $contact['status'] !== 'subscribed') return;

        $mailer = new Mailer();
        $subject = $config['subject'] ?? 'No Subject';
        $html = $config['html_content'] ?? '';

        // Basic personalization
        $replacements = [
            '{{first_name}}' => $contact['first_name'],
            '{{last_name}}' => $contact['last_name'],
            '{{email}}' => $contact['email'],
            '{{company}}' => $contact['company'],
        ];
        $subject = str_replace(array_keys($replacements), array_values($replacements), $subject);
        $html = str_replace(array_keys($replacements), array_values($replacements), $html);

        $result = $mailer->send($contact['email'], $subject, $html);

        $db->prepare("INSERT INTO email_events (automation_id, contact_id, message_id, type) VALUES (?, ?, ?, ?)")
            ->execute([$item['automation_id'], $contact['id'], $result['message_id'] ?? '', $result['success'] ? 'sent' : 'bounced']);
    }

    private static function processTagStep(array $item, array $config): void {
        $db = Database::getInstance();
        $tagName = $config['tag'] ?? '';
        if (!$tagName) return;
        $db->prepare("INSERT OR IGNORE INTO tags (name) VALUES (?)")->execute([$tagName]);
        $tag = $db->prepare("SELECT id FROM tags WHERE name = ?")->execute([$tagName]);
        $tag = $db->query("SELECT id FROM tags WHERE name = '{$tagName}'")->fetch();
        if ($tag) {
            $db->prepare("INSERT OR IGNORE INTO contact_tags (contact_id, tag_id) VALUES (?, ?)")->execute([$item['contact_id'], $tag['id']]);
        }
    }

    private static function processRemoveTagStep(array $item, array $config): void {
        $db = Database::getInstance();
        $tagName = $config['tag'] ?? '';
        if (!$tagName) return;
        $stmt = $db->prepare("SELECT id FROM tags WHERE name = ?");
        $stmt->execute([$tagName]);
        $tag = $stmt->fetch();
        if ($tag) {
            $db->prepare("DELETE FROM contact_tags WHERE contact_id = ? AND tag_id = ?")->execute([$item['contact_id'], $tag['id']]);
        }
    }

    private static function processFieldStep(array $item, array $config): void {
        $db = Database::getInstance();
        $field = $config['field'] ?? '';
        $value = $config['value'] ?? '';
        if (!$field) return;

        $allowed = ['first_name', 'last_name', 'company', 'phone', 'status'];
        if (in_array($field, $allowed)) {
            $db->prepare("UPDATE contacts SET {$field} = ?, updated_at = datetime('now') WHERE id = ?")
                ->execute([$value, $item['contact_id']]);
        }
    }

    private static function processListStep(array $item, array $config): void {
        $db = Database::getInstance();
        $listId = $config['list_id'] ?? 0;
        if (!$listId) return;
        $db->prepare("INSERT OR IGNORE INTO list_contacts (list_id, contact_id) VALUES (?, ?)")
            ->execute([$listId, $item['contact_id']]);
    }

    private static function processLeadScoreStep(array $item, array $config): void {
        $db = Database::getInstance();
        $change = (int)($config['score_change'] ?? 0);
        $db->prepare("UPDATE contacts SET lead_score = MAX(0, lead_score + ?), updated_at = datetime('now') WHERE id = ?")
            ->execute([$change, $item['contact_id']]);
    }

    private static function processWebhookStep(array $item, array $config): void {
        $url = $config['url'] ?? '';
        if (!$url) return;

        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM contacts WHERE id = ?");
        $stmt->execute([$item['contact_id']]);
        $contact = $stmt->fetch();

        $payload = json_encode([
            'event' => 'automation_step',
            'automation_id' => $item['automation_id'],
            'contact' => $contact,
            'timestamp' => date('c'),
        ]);

        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $payload,
            CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 10,
        ]);
        curl_exec($ch);
        curl_close($ch);
    }

    private static function queueNextStep(array $currentItem): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM automation_steps WHERE automation_id = ? AND step_order > (SELECT step_order FROM automation_steps WHERE id = ?) ORDER BY step_order LIMIT 1");
        $stmt->execute([$currentItem['automation_id'], $currentItem['step_id']]);
        $nextStep = $stmt->fetch();

        if ($nextStep) {
            $config = json_decode($nextStep['config'], true);
            $delay = self::calculateDelay($config);

            $db->prepare("INSERT INTO automation_queue (automation_id, step_id, contact_id, execute_at) VALUES (?, ?, ?, datetime('now', ?))")
                ->execute([$currentItem['automation_id'], $nextStep['id'], $currentItem['contact_id'], "+{$delay} seconds"]);
        } else {
            $db->prepare("UPDATE automations SET total_completed = total_completed + 1, updated_at = datetime('now') WHERE id = ?")
                ->execute([$currentItem['automation_id']]);
        }
    }

    private static function calculateDelay(array $config): int {
        if (!isset($config['delay'])) return 0;
        $delay = $config['delay'];
        $unit = $config['delay_unit'] ?? 'minutes';
        return match ($unit) {
            'minutes' => $delay * 60,
            'hours' => $delay * 3600,
            'days' => $delay * 86400,
            default => $delay,
        };
    }

    private static function checkTriggerConditions(array $config, array $data): bool {
        // Extensible trigger condition checking
        if (isset($config['list_id']) && isset($data['list_id'])) {
            if ($config['list_id'] != $data['list_id']) return false;
        }
        if (isset($config['tag']) && isset($data['tag'])) {
            if ($config['tag'] != $data['tag']) return false;
        }
        return true;
    }

    public static function getTriggerTypes(): void {
        Router::json([
            ['id' => 'contact_created', 'name' => 'Contact Created', 'description' => 'When a new contact is added'],
            ['id' => 'contact_subscribed', 'name' => 'Contact Subscribed', 'description' => 'When a contact subscribes'],
            ['id' => 'form_submitted', 'name' => 'Form Submitted', 'description' => 'When a form is submitted'],
            ['id' => 'tag_added', 'name' => 'Tag Added', 'description' => 'When a specific tag is added to a contact'],
            ['id' => 'list_joined', 'name' => 'Added to List', 'description' => 'When a contact is added to a specific list'],
            ['id' => 'email_opened', 'name' => 'Email Opened', 'description' => 'When a contact opens a specific campaign'],
            ['id' => 'link_clicked', 'name' => 'Link Clicked', 'description' => 'When a contact clicks a link in a campaign'],
            ['id' => 'date_based', 'name' => 'Date Based', 'description' => 'On a specific date or anniversary'],
            ['id' => 'manual', 'name' => 'Manual Trigger', 'description' => 'Triggered manually or via API'],
        ]);
    }
}
