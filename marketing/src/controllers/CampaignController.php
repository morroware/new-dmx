<?php
class CampaignController {
    public static function index(): void {
        $db = Database::getInstance();
        $page = (int)($_GET['page'] ?? 1);
        $status = $_GET['status'] ?? '';

        $where = '';
        $params = [];
        if ($status) { $where = 'WHERE c.status = ?'; $params[] = $status; }

        $query = "SELECT c.*, t.name as template_name, l.name as list_name
                  FROM campaigns c
                  LEFT JOIN templates t ON c.template_id = t.id
                  LEFT JOIN lists l ON c.list_id = l.id
                  {$where}
                  ORDER BY c.created_at DESC";

        $result = Router::paginate($db, $query, $params, $page);
        Router::json($result);
    }

    public static function show(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT c.*, t.name as template_name, l.name as list_name, l.contact_count as list_size
                              FROM campaigns c
                              LEFT JOIN templates t ON c.template_id = t.id
                              LEFT JOIN lists l ON c.list_id = l.id
                              WHERE c.id = ?");
        $stmt->execute([$params['id']]);
        $campaign = $stmt->fetch();
        if (!$campaign) { Router::json(['error' => 'Campaign not found'], 404); return; }

        // Stats breakdown
        $stmt = $db->prepare("SELECT type, COUNT(*) as count FROM email_events WHERE campaign_id = ? GROUP BY type");
        $stmt->execute([$params['id']]);
        $campaign['event_stats'] = [];
        foreach ($stmt->fetchAll() as $row) {
            $campaign['event_stats'][$row['type']] = (int)$row['count'];
        }

        // Hourly open/click distribution (for charts)
        $stmt = $db->prepare("
            SELECT strftime('%Y-%m-%d %H:00:00', created_at) as hour, type, COUNT(*) as count
            FROM email_events
            WHERE campaign_id = ? AND type IN ('opened', 'clicked')
            GROUP BY hour, type
            ORDER BY hour
        ");
        $stmt->execute([$params['id']]);
        $campaign['hourly_stats'] = $stmt->fetchAll();

        // Top clicked links
        $stmt = $db->prepare("
            SELECT json_extract(metadata, '$.url') as url, COUNT(*) as clicks
            FROM email_events
            WHERE campaign_id = ? AND type = 'clicked'
            GROUP BY url ORDER BY clicks DESC LIMIT 10
        ");
        $stmt->execute([$params['id']]);
        $campaign['top_links'] = $stmt->fetchAll();

        Router::json($campaign);
    }

    public static function store(): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        if (empty($data['name'])) { Router::json(['error' => 'Campaign name is required'], 422); return; }

        $stmt = $db->prepare("INSERT INTO campaigns (name, subject, from_name, from_email, reply_to, template_id, list_id, html_content, text_content, type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");

        // Get defaults from settings
        $settings = self::getSettings();

        $stmt->execute([
            $data['name'],
            $data['subject'] ?? '',
            $data['from_name'] ?? $settings['from_name'] ?? '',
            $data['from_email'] ?? $settings['from_email'] ?? '',
            $data['reply_to'] ?? $settings['reply_to'] ?? '',
            $data['template_id'] ?? null,
            $data['list_id'] ?? null,
            $data['html_content'] ?? '',
            $data['text_content'] ?? '',
            $data['type'] ?? 'regular',
        ]);

        $id = $db->lastInsertId();

        // If A/B test
        if (($data['type'] ?? '') === 'ab_test' && !empty($data['ab_config'])) {
            $ab = $data['ab_config'];
            $db->prepare("INSERT INTO ab_tests (campaign_id, variant_a_subject, variant_b_subject, variant_a_content, variant_b_content, split_percentage, winner_metric) VALUES (?, ?, ?, ?, ?, ?, ?)")
                ->execute([$id, $ab['variant_a_subject'] ?? '', $ab['variant_b_subject'] ?? '', $ab['variant_a_content'] ?? '', $ab['variant_b_content'] ?? '', $ab['split_percentage'] ?? 50, $ab['winner_metric'] ?? 'open_rate']);
        }

        ActivityLog::log('campaign_created', "Campaign created: {$data['name']}", ['campaign_id' => $id]);
        Router::json(['id' => $id, 'message' => 'Campaign created'], 201);
    }

    public static function update(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        $fields = ['name', 'subject', 'from_name', 'from_email', 'reply_to', 'template_id', 'list_id', 'html_content', 'text_content', 'status', 'scheduled_at'];
        $updates = [];
        $values = [];
        foreach ($fields as $field) {
            if (isset($data[$field])) {
                $updates[] = "{$field} = ?";
                $values[] = $data[$field];
            }
        }

        if ($updates) {
            $updates[] = "updated_at = datetime('now')";
            $values[] = $params['id'];
            $db->prepare("UPDATE campaigns SET " . implode(', ', $updates) . " WHERE id = ?")->execute($values);
        }

        Router::json(['message' => 'Campaign updated']);
    }

    public static function destroy(array $params): void {
        $db = Database::getInstance();
        $db->prepare("DELETE FROM campaigns WHERE id = ?")->execute([$params['id']]);
        Router::json(['message' => 'Campaign deleted']);
    }

    public static function duplicate(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM campaigns WHERE id = ?");
        $stmt->execute([$params['id']]);
        $campaign = $stmt->fetch();
        if (!$campaign) { Router::json(['error' => 'Not found'], 404); return; }

        $stmt = $db->prepare("INSERT INTO campaigns (name, subject, from_name, from_email, reply_to, template_id, list_id, html_content, text_content, type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");
        $stmt->execute([
            $campaign['name'] . ' (Copy)',
            $campaign['subject'],
            $campaign['from_name'],
            $campaign['from_email'],
            $campaign['reply_to'],
            $campaign['template_id'],
            $campaign['list_id'],
            $campaign['html_content'],
            $campaign['text_content'],
            $campaign['type'],
        ]);

        Router::json(['id' => $db->lastInsertId(), 'message' => 'Campaign duplicated'], 201);
    }

    public static function send(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT c.*, l.id as lid FROM campaigns c LEFT JOIN lists l ON c.list_id = l.id WHERE c.id = ?");
        $stmt->execute([$params['id']]);
        $campaign = $stmt->fetch();

        if (!$campaign) { Router::json(['error' => 'Campaign not found'], 404); return; }
        if (!$campaign['list_id']) { Router::json(['error' => 'No list assigned'], 422); return; }
        if (empty($campaign['subject'])) { Router::json(['error' => 'Subject is required'], 422); return; }
        if (empty($campaign['html_content'])) { Router::json(['error' => 'Email content is required'], 422); return; }

        // Get recipients
        $stmt = $db->prepare("
            SELECT c.* FROM contacts c
            JOIN list_contacts lc ON c.id = lc.contact_id
            WHERE lc.list_id = ? AND c.status = 'subscribed'
        ");
        $stmt->execute([$campaign['list_id']]);
        $recipients = $stmt->fetchAll();

        if (empty($recipients)) { Router::json(['error' => 'No subscribed contacts in list'], 422); return; }

        // Update campaign status
        $db->prepare("UPDATE campaigns SET status = 'sending', sent_at = datetime('now'), total_recipients = ?, updated_at = datetime('now') WHERE id = ?")
            ->execute([count($recipients), $params['id']]);

        $settings = self::getSettings();
        $mailer = new Mailer();
        $sent = 0;
        $failed = 0;
        $siteUrl = $settings['site_url'] ?? 'http://localhost:8080';

        foreach ($recipients as $contact) {
            $html = self::personalizeContent($campaign['html_content'], $contact, $campaign, $siteUrl);
            $text = self::personalizeContent($campaign['text_content'] ?: strip_tags($campaign['html_content']), $contact, $campaign, $siteUrl);

            // Add tracking pixel
            if ($settings['track_opens'] ?? true) {
                $trackPixelUrl = $siteUrl . "/track/open?cid={$params['id']}&uid={$contact['id']}&t=" . time();
                $html .= '<img src="' . htmlspecialchars($trackPixelUrl) . '" width="1" height="1" style="display:none" alt="">';
            }

            // Wrap links for click tracking
            if ($settings['track_clicks'] ?? true) {
                $html = self::wrapLinks($html, $params['id'], $contact['id'], $siteUrl);
            }

            // Unsubscribe link
            $unsubUrl = $siteUrl . "/unsubscribe?uid={$contact['id']}&cid={$params['id']}";
            $html = str_replace('{{unsubscribe_url}}', $unsubUrl, $html);
            $text = str_replace('{{unsubscribe_url}}', $unsubUrl, $text);

            $result = $mailer->send(
                $contact['email'],
                self::personalizeContent($campaign['subject'], $contact, $campaign, $siteUrl),
                $html,
                $text,
                [
                    'from_name' => $campaign['from_name'],
                    'reply_to' => $campaign['reply_to'],
                    'list_unsubscribe' => $unsubUrl,
                ]
            );

            if ($result['success']) {
                $sent++;
                $db->prepare("INSERT INTO email_events (campaign_id, contact_id, message_id, type) VALUES (?, ?, ?, 'sent')")
                    ->execute([$params['id'], $contact['id'], $result['message_id']]);
            } else {
                $failed++;
                $db->prepare("INSERT INTO email_events (campaign_id, contact_id, type, metadata) VALUES (?, ?, 'bounced', ?)")
                    ->execute([$params['id'], $contact['id'], json_encode(['error' => $result['error']])]);
            }
        }

        $status = ($sent > 0) ? 'sent' : 'failed';
        $db->prepare("UPDATE campaigns SET status = ?, total_sent = ?, total_bounced = ?, completed_at = datetime('now'), updated_at = datetime('now') WHERE id = ?")
            ->execute([$status, $sent, $failed, $params['id']]);

        ActivityLog::log('campaign_sent', "Campaign '{$campaign['name']}' sent to {$sent} recipients", ['campaign_id' => $params['id']]);
        Router::json(['message' => "Sent to {$sent} recipients, {$failed} failed", 'sent' => $sent, 'failed' => $failed]);
    }

    public static function schedule(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();
        if (empty($data['scheduled_at'])) { Router::json(['error' => 'Schedule time is required'], 422); return; }

        $db->prepare("UPDATE campaigns SET status = 'scheduled', scheduled_at = ?, updated_at = datetime('now') WHERE id = ?")
            ->execute([$data['scheduled_at'], $params['id']]);

        Router::json(['message' => 'Campaign scheduled']);
    }

    public static function preview(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM campaigns WHERE id = ?");
        $stmt->execute([$params['id']]);
        $campaign = $stmt->fetch();
        if (!$campaign) { Router::json(['error' => 'Not found'], 404); return; }

        $contact = [
            'email' => 'preview@example.com',
            'first_name' => 'John',
            'last_name' => 'Doe',
            'company' => 'Acme Inc',
        ];

        $html = self::personalizeContent($campaign['html_content'], $contact, $campaign, '');
        Router::json(['html' => $html, 'subject' => self::personalizeContent($campaign['subject'], $contact, $campaign, '')]);
    }

    public static function sendTest(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();
        $testEmail = $data['email'] ?? '';
        if (!$testEmail || !filter_var($testEmail, FILTER_VALIDATE_EMAIL)) {
            Router::json(['error' => 'Valid email required'], 422);
            return;
        }

        $stmt = $db->prepare("SELECT * FROM campaigns WHERE id = ?");
        $stmt->execute([$params['id']]);
        $campaign = $stmt->fetch();
        if (!$campaign) { Router::json(['error' => 'Not found'], 404); return; }

        $contact = ['email' => $testEmail, 'first_name' => 'Test', 'last_name' => 'User', 'company' => 'Test'];
        $html = self::personalizeContent($campaign['html_content'], $contact, $campaign, '');

        $mailer = new Mailer();
        $result = $mailer->send($testEmail, '[TEST] ' . $campaign['subject'], $html);

        Router::json($result);
    }

    private static function personalizeContent(string $content, array $contact, array $campaign, string $siteUrl): string {
        $replacements = [
            '{{email}}' => $contact['email'] ?? '',
            '{{first_name}}' => $contact['first_name'] ?? '',
            '{{last_name}}' => $contact['last_name'] ?? '',
            '{{full_name}}' => trim(($contact['first_name'] ?? '') . ' ' . ($contact['last_name'] ?? '')),
            '{{company}}' => $contact['company'] ?? '',
            '{{campaign_name}}' => $campaign['name'] ?? '',
            '{{current_year}}' => date('Y'),
            '{{current_date}}' => date('F j, Y'),
        ];
        return str_replace(array_keys($replacements), array_values($replacements), $content);
    }

    private static function wrapLinks(string $html, int $campaignId, int $contactId, string $siteUrl): string {
        return preg_replace_callback(
            '/<a\s+([^>]*?)href=["\']([^"\']+)["\']([^>]*?)>/i',
            function ($matches) use ($campaignId, $contactId, $siteUrl) {
                $url = $matches[2];
                if (str_starts_with($url, '#') || str_contains($url, 'unsubscribe') || str_contains($url, '/track/')) {
                    return $matches[0];
                }
                $trackUrl = $siteUrl . '/track/click?cid=' . $campaignId . '&uid=' . $contactId . '&url=' . urlencode($url);
                return '<a ' . $matches[1] . 'href="' . htmlspecialchars($trackUrl) . '"' . $matches[3] . '>';
            },
            $html
        );
    }

    private static function getSettings(): array {
        $db = Database::getInstance();
        $rows = $db->query("SELECT key, value FROM settings")->fetchAll();
        $settings = [];
        foreach ($rows as $row) $settings[$row['key']] = $row['value'];
        return $settings;
    }
}
