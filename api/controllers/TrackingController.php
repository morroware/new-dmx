<?php
class TrackingController {
    public static function open(): void {
        $cid = $_GET['cid'] ?? 0; $uid = $_GET['uid'] ?? 0;
        if ($cid && $uid) {
            $db = Database::getInstance();
            $stmt = $db->prepare("SELECT id FROM email_events WHERE campaign_id=? AND contact_id=? AND type='opened' LIMIT 1");
            $stmt->execute([$cid,$uid]); $first = !$stmt->fetch();
            $db->prepare("INSERT INTO email_events (campaign_id,contact_id,type,ip_address,user_agent) VALUES (?,?,'opened',?,?)")
                ->execute([$cid,$uid,$_SERVER['REMOTE_ADDR']??'',$_SERVER['HTTP_USER_AGENT']??'']);
            if ($first) {
                $db->prepare("UPDATE campaigns SET total_opened=total_opened+1 WHERE id=?")->execute([$cid]);
                $db->prepare("UPDATE contacts SET lead_score=lead_score+1 WHERE id=?")->execute([$uid]);
            }
        }
        header('Content-Type: image/gif');
        header('Cache-Control: no-store');
        echo base64_decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7');
        exit;
    }

    public static function click(): void {
        $cid = $_GET['cid'] ?? 0; $uid = $_GET['uid'] ?? 0; $url = $_GET['url'] ?? '';
        if (!$url) { http_response_code(400); exit; }
        if ($cid && $uid) {
            $db = Database::getInstance();
            $db->prepare("INSERT INTO email_events (campaign_id,contact_id,type,metadata,ip_address) VALUES (?,?,'clicked',?,?)")
                ->execute([$cid,$uid,json_encode(['url'=>$url]),$_SERVER['REMOTE_ADDR']??'']);
            $stmt = $db->prepare("SELECT COUNT(*) FROM email_events WHERE campaign_id=? AND contact_id=? AND type='clicked'");
            $stmt->execute([$cid,$uid]);
            if ((int)$stmt->fetchColumn() === 1) $db->prepare("UPDATE campaigns SET total_clicked=total_clicked+1 WHERE id=?")->execute([$cid]);
            $db->prepare("UPDATE contacts SET lead_score=lead_score+2 WHERE id=?")->execute([$uid]);
        }
        header('Location: '.$url, true, 302); exit;
    }

    public static function unsubscribe(): void {
        $uid = $_GET['uid'] ?? $_POST['uid'] ?? 0;
        $cid = $_GET['cid'] ?? $_POST['cid'] ?? 0;
        if (!$uid) { echo '<h1>Invalid link</h1>'; exit; }
        $db = Database::getInstance();
        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            $db->prepare("UPDATE contacts SET status='unsubscribed',unsubscribed_at=datetime('now') WHERE id=?")->execute([$uid]);
            if ($cid) {
                $db->prepare("INSERT INTO email_events (campaign_id,contact_id,type) VALUES (?,?,'unsubscribed')")->execute([$cid,$uid]);
                $db->prepare("UPDATE campaigns SET total_unsubscribed=total_unsubscribed+1 WHERE id=?")->execute([$cid]);
            }
            header('Content-Type: text/html');
            echo '<!DOCTYPE html><html><body style="margin:0;background:#0f0f12;color:#f2f2f4;font-family:Arial,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;"><div style="text-align:center;"><div style="font-size:48px;color:#22C55E;margin-bottom:16px;">&#10003;</div><p>You have been unsubscribed.</p></div></body></html>';
            exit;
        }
        $stmt = $db->prepare("SELECT email FROM contacts WHERE id=?"); $stmt->execute([$uid]); $c = $stmt->fetch();
        $email = htmlspecialchars($c['email'] ?? 'unknown');
        header('Content-Type: text/html');
        echo "<!DOCTYPE html><html><body style=\"margin:0;background:#0f0f12;color:#f2f2f4;font-family:Arial,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;\"><div style=\"background:#1a1a1f;border:1px solid #2a2a32;border-radius:12px;padding:40px;max-width:480px;text-align:center;\"><h2>Unsubscribe</h2><p style=\"color:#a8a8b4;\">Unsubscribe <strong style=\"color:#FF6B35;\">{$email}</strong>?</p><form method=\"POST\"><input type=\"hidden\" name=\"uid\" value=\"{$uid}\"><input type=\"hidden\" name=\"cid\" value=\"{$cid}\"><button type=\"submit\" style=\"background:#EF4444;color:#fff;border:none;padding:14px 32px;border-radius:8px;font-size:16px;cursor:pointer;font-weight:bold;\">Unsubscribe</button></form><a href=\"javascript:history.back()\" style=\"display:block;margin-top:16px;color:#65656F;\">Cancel</a></div></body></html>";
        exit;
    }
}
