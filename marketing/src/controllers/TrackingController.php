<?php
class TrackingController {
    /**
     * Track email open via 1x1 pixel
     */
    public static function trackOpen(): void {
        $campaignId = $_GET['cid'] ?? 0;
        $contactId = $_GET['uid'] ?? 0;

        if ($campaignId && $contactId) {
            $db = Database::getInstance();
            $ip = $_SERVER['REMOTE_ADDR'] ?? '';
            $ua = $_SERVER['HTTP_USER_AGENT'] ?? '';

            // Only record first open per contact per campaign
            $stmt = $db->prepare("SELECT id FROM email_events WHERE campaign_id = ? AND contact_id = ? AND type = 'opened' LIMIT 1");
            $stmt->execute([$campaignId, $contactId]);
            $isFirst = !$stmt->fetch();

            $db->prepare("INSERT INTO email_events (campaign_id, contact_id, type, ip_address, user_agent) VALUES (?, ?, 'opened', ?, ?)")
                ->execute([$campaignId, $contactId, $ip, $ua]);

            if ($isFirst) {
                $db->prepare("UPDATE campaigns SET total_opened = total_opened + 1, updated_at = datetime('now') WHERE id = ?")
                    ->execute([$campaignId]);

                // Update lead score
                $db->prepare("UPDATE contacts SET lead_score = lead_score + 1, updated_at = datetime('now') WHERE id = ?")
                    ->execute([$contactId]);

                // Trigger automations
                AutomationController::triggerForContact('email_opened', (int)$contactId, ['campaign_id' => $campaignId]);
            }
        }

        // Return 1x1 transparent GIF
        header('Content-Type: image/gif');
        header('Cache-Control: no-store, no-cache, must-revalidate');
        echo base64_decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7');
        exit;
    }

    /**
     * Track link click and redirect
     */
    public static function trackClick(): void {
        $campaignId = $_GET['cid'] ?? 0;
        $contactId = $_GET['uid'] ?? 0;
        $url = $_GET['url'] ?? '';

        if (!$url) {
            http_response_code(400);
            echo 'Missing URL';
            exit;
        }

        if ($campaignId && $contactId) {
            $db = Database::getInstance();
            $ip = $_SERVER['REMOTE_ADDR'] ?? '';
            $ua = $_SERVER['HTTP_USER_AGENT'] ?? '';

            // Record click
            $db->prepare("INSERT INTO email_events (campaign_id, contact_id, type, metadata, ip_address, user_agent) VALUES (?, ?, 'clicked', ?, ?, ?)")
                ->execute([$campaignId, $contactId, json_encode(['url' => $url]), $ip, $ua]);

            // Update campaign stats (unique clicks)
            $stmt = $db->prepare("SELECT COUNT(*) FROM email_events WHERE campaign_id = ? AND contact_id = ? AND type = 'clicked'");
            $stmt->execute([$campaignId, $contactId]);
            if ((int)$stmt->fetchColumn() === 1) {
                $db->prepare("UPDATE campaigns SET total_clicked = total_clicked + 1, updated_at = datetime('now') WHERE id = ?")
                    ->execute([$campaignId]);
            }

            // Update lead score
            $db->prepare("UPDATE contacts SET lead_score = lead_score + 2, updated_at = datetime('now') WHERE id = ?")
                ->execute([$contactId]);

            // Trigger automations
            AutomationController::triggerForContact('link_clicked', (int)$contactId, ['campaign_id' => $campaignId, 'url' => $url]);
        }

        // Redirect to original URL
        header('Location: ' . $url, true, 302);
        exit;
    }

    /**
     * Handle unsubscribe
     */
    public static function unsubscribe(): void {
        $contactId = $_GET['uid'] ?? $_POST['uid'] ?? 0;
        $campaignId = $_GET['cid'] ?? $_POST['cid'] ?? 0;

        if (!$contactId) {
            self::renderUnsubscribePage('Invalid unsubscribe link.', true);
            return;
        }

        $db = Database::getInstance();

        // Handle POST (confirmation)
        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            $db->prepare("UPDATE contacts SET status = 'unsubscribed', unsubscribed_at = datetime('now'), updated_at = datetime('now') WHERE id = ?")
                ->execute([$contactId]);

            if ($campaignId) {
                $db->prepare("INSERT INTO email_events (campaign_id, contact_id, type) VALUES (?, ?, 'unsubscribed')")
                    ->execute([$campaignId, $contactId]);
                $db->prepare("UPDATE campaigns SET total_unsubscribed = total_unsubscribed + 1 WHERE id = ?")
                    ->execute([$campaignId]);
            }

            ActivityLog::log('contact_unsubscribed', "Contact unsubscribed: ID {$contactId}", ['contact_id' => $contactId, 'campaign_id' => $campaignId]);

            self::renderUnsubscribePage('You have been successfully unsubscribed. You will no longer receive emails from us.', false);
            return;
        }

        // Show confirmation page
        $stmt = $db->prepare("SELECT email FROM contacts WHERE id = ?");
        $stmt->execute([$contactId]);
        $contact = $stmt->fetch();

        if (!$contact) {
            self::renderUnsubscribePage('Contact not found.', true);
            return;
        }

        $email = htmlspecialchars($contact['email']);
        $settings = [];
        $rows = $db->query("SELECT key, value FROM settings WHERE key IN ('site_name', 'company_name')")->fetchAll();
        foreach ($rows as $r) $settings[$r['key']] = $r['value'];
        $siteName = htmlspecialchars($settings['site_name'] ?? APP_NAME);

        header('Content-Type: text/html; charset=utf-8');
        echo <<<HTML
<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribe - {$siteName}</title>
<style>body{font-family:Arial,sans-serif;background:#f4f4f4;margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#fff;border-radius:12px;padding:40px;max-width:480px;width:100%;text-align:center;box-shadow:0 4px 12px rgba(0,0,0,.08)}
h2{color:#1e293b;margin:0 0 12px}p{color:#64748b;margin:0 0 24px}
.email{color:#6366f1;font-weight:bold}
button{background:#ef4444;color:#fff;border:none;padding:14px 32px;border-radius:8px;font-size:16px;cursor:pointer;font-weight:bold}
button:hover{background:#dc2626}.cancel{display:block;margin-top:16px;color:#64748b;text-decoration:none}</style>
</head><body><div class="card">
<h2>Unsubscribe</h2>
<p>Are you sure you want to unsubscribe <span class="email">{$email}</span> from our mailing list?</p>
<form method="POST">
<input type="hidden" name="uid" value="{$contactId}">
<input type="hidden" name="cid" value="{$campaignId}">
<button type="submit">Unsubscribe</button>
</form>
<a href="javascript:history.back()" class="cancel">Cancel</a>
</div></body></html>
HTML;
        exit;
    }

    private static function renderUnsubscribePage(string $message, bool $isError): void {
        $color = $isError ? '#ef4444' : '#10b981';
        $icon = $isError ? '&#10007;' : '&#10003;';
        header('Content-Type: text/html; charset=utf-8');
        echo <<<HTML
<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribe</title>
<style>body{font-family:Arial,sans-serif;background:#f4f4f4;margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#fff;border-radius:12px;padding:40px;max-width:480px;width:100%;text-align:center;box-shadow:0 4px 12px rgba(0,0,0,.08)}
.icon{font-size:48px;color:{$color};margin-bottom:16px}p{color:#64748b;font-size:16px}</style>
</head><body><div class="card">
<div class="icon">{$icon}</div>
<p>{$message}</p>
</div></body></html>
HTML;
        exit;
    }
}
