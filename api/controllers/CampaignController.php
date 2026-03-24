<?php
class CampaignController {
    public static function index(): void {
        $db = Database::getInstance();
        $status = $_GET['status'] ?? '';
        $w = ''; $p = [];
        if ($status) { $w = 'WHERE c.status=?'; $p[] = $status; }
        $result = Router::paginate($db,
            "SELECT c.*,t.name as template_name,l.name as list_name FROM campaigns c LEFT JOIN templates t ON c.template_id=t.id LEFT JOIN lists l ON c.list_id=l.id {$w} ORDER BY c.created_at DESC",
            $p, (int)($_GET['page'] ?? 1)
        );
        Router::json($result);
    }

    public static function show(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT c.*,t.name as template_name,l.name as list_name FROM campaigns c LEFT JOIN templates t ON c.template_id=t.id LEFT JOIN lists l ON c.list_id=l.id WHERE c.id=?");
        $stmt->execute([$p['id']]); $c = $stmt->fetch();
        if (!$c) { Router::json(['error' => 'Not found'], 404); return; }
        $stmt = $db->prepare("SELECT type,COUNT(*) as count FROM email_events WHERE campaign_id=? GROUP BY type");
        $stmt->execute([$p['id']]); $c['event_stats'] = [];
        foreach ($stmt->fetchAll() as $r) $c['event_stats'][$r['type']] = (int)$r['count'];
        $stmt = $db->prepare("SELECT json_extract(metadata,'$.url') as url,COUNT(*) as clicks FROM email_events WHERE campaign_id=? AND type='clicked' GROUP BY url ORDER BY clicks DESC LIMIT 10");
        $stmt->execute([$p['id']]); $c['top_links'] = $stmt->fetchAll();
        Router::json($c);
    }

    public static function store(): void {
        $db = Database::getInstance(); $d = Router::body();
        if (empty($d['name'])) { Router::json(['error' => 'Name required'], 422); return; }
        $s = Router::getSettings(['from_name','from_email','reply_to']);
        $db->prepare("INSERT INTO campaigns (name,type,subject,from_name,from_email,reply_to,template_id,list_id,html_content,text_content) VALUES (?,?,?,?,?,?,?,?,?,?)")
            ->execute([$d['name'],$d['type']??'email',$d['subject']??'',$d['from_name']??$s['from_name']??'',$d['from_email']??$s['from_email']??'',$d['reply_to']??$s['reply_to']??'',$d['template_id']??null,$d['list_id']??null,$d['html_content']??'',$d['text_content']??'']);
        Router::json(['id' => $db->lastInsertId(), 'message' => 'Campaign created'], 201);
    }

    public static function update(array $p): void {
        $db = Database::getInstance(); $d = Router::body();
        $fields = []; $vals = [];
        foreach (['name','type','subject','from_name','from_email','reply_to','template_id','list_id','html_content','text_content','status','scheduled_at'] as $f) {
            if (isset($d[$f])) { $fields[] = "{$f}=?"; $vals[] = $d[$f]; }
        }
        if ($fields) { $fields[] = "updated_at=datetime('now')"; $vals[] = $p['id'];
            $db->prepare("UPDATE campaigns SET ".implode(',',$fields)." WHERE id=?")->execute($vals); }
        Router::json(['message' => 'Updated']);
    }

    public static function destroy(array $p): void {
        Database::getInstance()->prepare("DELETE FROM campaigns WHERE id=?")->execute([$p['id']]);
        Router::json(['message' => 'Deleted']);
    }

    public static function send(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM campaigns WHERE id=?"); $stmt->execute([$p['id']]); $c = $stmt->fetch();
        if (!$c) { Router::json(['error' => 'Not found'], 404); return; }
        if (!$c['list_id']) { Router::json(['error' => 'No list assigned'], 422); return; }
        if (!$c['html_content']) { Router::json(['error' => 'Content required'], 422); return; }

        $stmt = $db->prepare("SELECT c.* FROM contacts c JOIN list_contacts lc ON c.id=lc.contact_id WHERE lc.list_id=? AND c.status='subscribed'");
        $stmt->execute([$c['list_id']]); $recipients = $stmt->fetchAll();
        if (!$recipients) { Router::json(['error' => 'No subscribers in list'], 422); return; }

        $db->prepare("UPDATE campaigns SET status='sending',sent_at=datetime('now'),total_recipients=? WHERE id=?")
            ->execute([count($recipients),$p['id']]);

        $mailer = new Mailer(); $sent = 0; $failed = 0;
        $siteUrl = Router::getSetting('site_url') ?: 'http://localhost:8080';

        foreach ($recipients as $contact) {
            $html = self::personalize($c['html_content'], $contact);
            $text = self::personalize($c['text_content'] ?: strip_tags($c['html_content']), $contact);
            $subj = self::personalize($c['subject'], $contact);

            // Tracking pixel
            $html .= '<img src="'.htmlspecialchars($siteUrl."/api/track/open?cid={$p['id']}&uid={$contact['id']}").'" width="1" height="1" style="display:none" alt="">';

            // Unsubscribe
            $unsub = $siteUrl."/api/unsubscribe?uid={$contact['id']}&cid={$p['id']}";
            $html = str_replace('{{unsubscribe_url}}', $unsub, $html);

            $result = $mailer->send($contact['email'], $subj, $html, $text, ['list_unsubscribe' => $unsub]);
            if ($result['success']) {
                $sent++;
                $db->prepare("INSERT INTO email_events (campaign_id,contact_id,message_id,type) VALUES (?,?,?,'sent')")
                    ->execute([$p['id'],$contact['id'],$result['message_id']]);
            } else { $failed++; }
        }

        $db->prepare("UPDATE campaigns SET status=?,total_sent=?,total_bounced=?,completed_at=datetime('now') WHERE id=?")
            ->execute([$sent > 0 ? 'sent' : 'failed', $sent, $failed, $p['id']]);
        logActivity('campaign_sent', "Campaign sent to {$sent} recipients");
        Router::json(['sent' => $sent, 'failed' => $failed]);
    }

    public static function duplicate(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM campaigns WHERE id=?"); $stmt->execute([$p['id']]); $c = $stmt->fetch();
        if (!$c) { Router::json(['error' => 'Not found'], 404); return; }
        $db->prepare("INSERT INTO campaigns (name,type,subject,from_name,from_email,reply_to,template_id,list_id,html_content,text_content) VALUES (?,?,?,?,?,?,?,?,?,?)")
            ->execute([$c['name'].' (Copy)',$c['type'],$c['subject'],$c['from_name'],$c['from_email'],$c['reply_to'],$c['template_id'],$c['list_id'],$c['html_content'],$c['text_content']]);
        Router::json(['id' => $db->lastInsertId()], 201);
    }

    public static function preview(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM campaigns WHERE id=?"); $stmt->execute([$p['id']]); $c = $stmt->fetch();
        if (!$c) { Router::json(['error' => 'Not found'], 404); return; }
        $fake = ['email'=>'preview@example.com','first_name'=>'John','last_name'=>'Doe','company'=>'Acme'];
        Router::json(['html' => self::personalize($c['html_content'], $fake), 'subject' => self::personalize($c['subject'], $fake)]);
    }

    public static function sendTest(array $p): void {
        $d = Router::body(); $email = $d['email'] ?? '';
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) { Router::json(['error' => 'Valid email required'], 422); return; }
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM campaigns WHERE id=?"); $stmt->execute([$p['id']]); $c = $stmt->fetch();
        if (!$c) { Router::json(['error' => 'Not found'], 404); return; }
        $fake = ['email'=>$email,'first_name'=>'Test','last_name'=>'User','company'=>'Test'];
        $mailer = new Mailer();
        Router::json($mailer->send($email, '[TEST] '.$c['subject'], self::personalize($c['html_content'], $fake)));
    }

    private static function personalize(string $content, array $contact): string {
        return str_replace(
            ['{{email}}','{{first_name}}','{{last_name}}','{{full_name}}','{{company}}','{{current_year}}','{{current_date}}'],
            [$contact['email']??'',$contact['first_name']??'',$contact['last_name']??'',trim(($contact['first_name']??'').' '.($contact['last_name']??'')),$contact['company']??'',date('Y'),date('F j, Y')],
            $content
        );
    }
}
