<?php
class DashboardController {
    public static function stats(): void {
        $db = Database::getInstance();
        $q = fn($sql) => (int)$db->query($sql)->fetchColumn();

        Router::json([
            'total_contacts' => $q("SELECT COUNT(*) FROM contacts"),
            'subscribed' => $q("SELECT COUNT(*) FROM contacts WHERE status='subscribed'"),
            'new_contacts_week' => $q("SELECT COUNT(*) FROM contacts WHERE created_at>=datetime('now','-7 days')"),
            'new_contacts_month' => $q("SELECT COUNT(*) FROM contacts WHERE created_at>=datetime('now','-30 days')"),
            'total_campaigns' => $q("SELECT COUNT(*) FROM campaigns"),
            'sent_campaigns' => $q("SELECT COUNT(*) FROM campaigns WHERE status='sent'"),
            'draft_campaigns' => $q("SELECT COUNT(*) FROM campaigns WHERE status='draft'"),
            'total_sent' => $q("SELECT COALESCE(SUM(total_sent),0) FROM campaigns"),
            'total_opened' => $q("SELECT COUNT(*) FROM email_events WHERE type='opened'"),
            'total_clicked' => $q("SELECT COUNT(*) FROM email_events WHERE type='clicked'"),
            'total_social_posts' => $q("SELECT COUNT(*) FROM social_posts"),
            'published_posts' => $q("SELECT COUNT(*) FROM social_posts WHERE status='published'"),
            'scheduled_posts' => $q("SELECT COUNT(*) FROM social_posts WHERE status='scheduled'"),
            'active_automations' => $q("SELECT COUNT(*) FROM automations WHERE status='active'"),
            'total_forms' => $q("SELECT COUNT(*) FROM forms"),
            'total_submissions' => $q("SELECT COUNT(*) FROM form_submissions"),
            'total_lists' => $q("SELECT COUNT(*) FROM lists"),
            'total_tags' => $q("SELECT COUNT(*) FROM tags"),
            'total_templates' => $q("SELECT COUNT(*) FROM templates"),
            'total_pages' => $q("SELECT COUNT(*) FROM landing_pages"),
        ]);
    }

    public static function charts(): void {
        $db = Database::getInstance();
        $period = $_GET['period'] ?? '30';

        $contactGrowth = $db->prepare("SELECT date(created_at) as date, COUNT(*) as count FROM contacts WHERE created_at>=datetime('now','-'||?||' days') GROUP BY date(created_at) ORDER BY date");
        $contactGrowth->execute([$period]);

        $emailEvents = $db->prepare("SELECT date(created_at) as date, type, COUNT(*) as count FROM email_events WHERE created_at>=datetime('now','-'||?||' days') GROUP BY date(created_at),type ORDER BY date");
        $emailEvents->execute([$period]);

        $socialPosts = $db->prepare("SELECT date(created_at) as date, COUNT(*) as count FROM social_posts WHERE created_at>=datetime('now','-'||?||' days') GROUP BY date(created_at) ORDER BY date");
        $socialPosts->execute([$period]);

        $topCampaigns = $db->query("SELECT name,total_sent,total_opened,total_clicked, CASE WHEN total_sent>0 THEN ROUND(total_opened*100.0/total_sent,1) ELSE 0 END as open_rate FROM campaigns WHERE status='sent' AND total_sent>0 ORDER BY open_rate DESC LIMIT 5")->fetchAll();

        $contactSources = $db->query("SELECT source, COUNT(*) as count FROM contacts GROUP BY source ORDER BY count DESC")->fetchAll();

        Router::json([
            'contact_growth' => $contactGrowth->fetchAll(),
            'email_events' => $emailEvents->fetchAll(),
            'social_posts' => $socialPosts->fetchAll(),
            'top_campaigns' => $topCampaigns,
            'contact_sources' => $contactSources,
        ]);
    }

    public static function activity(): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?");
        $stmt->execute([(int)($_GET['limit'] ?? 20)]);
        Router::json($stmt->fetchAll());
    }

    public static function calendar(): void {
        $db = Database::getInstance();
        $start = $_GET['start'] ?? date('Y-m-01');
        $end = $_GET['end'] ?? date('Y-m-t');
        $stmt = $db->prepare("SELECT * FROM calendar_events WHERE start_date BETWEEN ? AND ? ORDER BY start_date");
        $stmt->execute([$start, $end]);
        Router::json($stmt->fetchAll());
    }

    public static function calendarStore(): void {
        $db = Database::getInstance(); $d = Router::body();
        $db->prepare("INSERT INTO calendar_events (title,description,type,start_date,end_date,color,all_day,status) VALUES (?,?,?,?,?,?,?,?)")
            ->execute([$d['title']??'',$d['description']??'',$d['type']??'event',$d['start_date']??date('Y-m-d'),$d['end_date']??null,$d['color']??'#FF6B35',$d['all_day']??1,$d['status']??'planned']);
        Router::json(['id' => $db->lastInsertId()], 201);
    }

    public static function calendarUpdate(array $p): void {
        $db = Database::getInstance(); $d = Router::body();
        $f = []; $v = [];
        foreach (['title','description','type','start_date','end_date','color','all_day','status'] as $k) {
            if (isset($d[$k])) { $f[] = "{$k}=?"; $v[] = $d[$k]; }
        }
        if ($f) { $f[] = "updated_at=datetime('now')"; $v[] = $p['id'];
            $db->prepare("UPDATE calendar_events SET ".implode(',',$f)." WHERE id=?")->execute($v); }
        Router::json(['message' => 'Updated']);
    }

    public static function calendarDelete(array $p): void {
        Database::getInstance()->prepare("DELETE FROM calendar_events WHERE id=?")->execute([$p['id']]);
        Router::json(['message' => 'Deleted']);
    }
}
