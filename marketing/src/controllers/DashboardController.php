<?php
class DashboardController {
    public static function stats(): void {
        $db = Database::getInstance();

        $stats = [];

        // Contacts
        $stats['total_contacts'] = (int)$db->query("SELECT COUNT(*) FROM contacts")->fetchColumn();
        $stats['subscribed_contacts'] = (int)$db->query("SELECT COUNT(*) FROM contacts WHERE status = 'subscribed'")->fetchColumn();
        $stats['unsubscribed_contacts'] = (int)$db->query("SELECT COUNT(*) FROM contacts WHERE status = 'unsubscribed'")->fetchColumn();
        $stats['new_contacts_today'] = (int)$db->query("SELECT COUNT(*) FROM contacts WHERE date(created_at) = date('now')")->fetchColumn();
        $stats['new_contacts_week'] = (int)$db->query("SELECT COUNT(*) FROM contacts WHERE created_at >= datetime('now', '-7 days')")->fetchColumn();
        $stats['new_contacts_month'] = (int)$db->query("SELECT COUNT(*) FROM contacts WHERE created_at >= datetime('now', '-30 days')")->fetchColumn();

        // Campaigns
        $stats['total_campaigns'] = (int)$db->query("SELECT COUNT(*) FROM campaigns")->fetchColumn();
        $stats['sent_campaigns'] = (int)$db->query("SELECT COUNT(*) FROM campaigns WHERE status = 'sent'")->fetchColumn();
        $stats['draft_campaigns'] = (int)$db->query("SELECT COUNT(*) FROM campaigns WHERE status = 'draft'")->fetchColumn();
        $stats['scheduled_campaigns'] = (int)$db->query("SELECT COUNT(*) FROM campaigns WHERE status = 'scheduled'")->fetchColumn();

        // Email stats
        $stats['total_sent'] = (int)$db->query("SELECT COALESCE(SUM(total_sent), 0) FROM campaigns")->fetchColumn();
        $stats['total_opened'] = (int)$db->query("SELECT COUNT(*) FROM email_events WHERE type = 'opened'")->fetchColumn();
        $stats['total_clicked'] = (int)$db->query("SELECT COUNT(*) FROM email_events WHERE type = 'clicked'")->fetchColumn();
        $stats['avg_open_rate'] = $stats['total_sent'] > 0 ? round(($stats['total_opened'] / $stats['total_sent']) * 100, 1) : 0;
        $stats['avg_click_rate'] = $stats['total_sent'] > 0 ? round(($stats['total_clicked'] / $stats['total_sent']) * 100, 1) : 0;

        // Automations
        $stats['active_automations'] = (int)$db->query("SELECT COUNT(*) FROM automations WHERE status = 'active'")->fetchColumn();
        $stats['total_automations'] = (int)$db->query("SELECT COUNT(*) FROM automations")->fetchColumn();

        // Forms
        $stats['total_forms'] = (int)$db->query("SELECT COUNT(*) FROM forms")->fetchColumn();
        $stats['total_form_submissions'] = (int)$db->query("SELECT COUNT(*) FROM form_submissions")->fetchColumn();
        $stats['form_submissions_today'] = (int)$db->query("SELECT COUNT(*) FROM form_submissions WHERE date(created_at) = date('now')")->fetchColumn();

        // Landing pages
        $stats['total_landing_pages'] = (int)$db->query("SELECT COUNT(*) FROM landing_pages")->fetchColumn();
        $stats['published_pages'] = (int)$db->query("SELECT COUNT(*) FROM landing_pages WHERE status = 'published'")->fetchColumn();

        // Lists
        $stats['total_lists'] = (int)$db->query("SELECT COUNT(*) FROM lists")->fetchColumn();

        // Tags
        $stats['total_tags'] = (int)$db->query("SELECT COUNT(*) FROM tags")->fetchColumn();

        Router::json($stats);
    }

    public static function charts(): void {
        $db = Database::getInstance();
        $period = $_GET['period'] ?? '30';

        // Contact growth over time
        $stmt = $db->prepare("
            SELECT date(created_at) as date, COUNT(*) as count
            FROM contacts
            WHERE created_at >= datetime('now', '-' || ? || ' days')
            GROUP BY date(created_at)
            ORDER BY date
        ");
        $stmt->execute([$period]);
        $contactGrowth = $stmt->fetchAll();

        // Email events over time
        $stmt = $db->prepare("
            SELECT date(created_at) as date, type, COUNT(*) as count
            FROM email_events
            WHERE created_at >= datetime('now', '-' || ? || ' days')
            GROUP BY date(created_at), type
            ORDER BY date
        ");
        $stmt->execute([$period]);
        $emailEvents = $stmt->fetchAll();

        // Form submissions over time
        $stmt = $db->prepare("
            SELECT date(created_at) as date, COUNT(*) as count
            FROM form_submissions
            WHERE created_at >= datetime('now', '-' || ? || ' days')
            GROUP BY date(created_at)
            ORDER BY date
        ");
        $stmt->execute([$period]);
        $formSubmissions = $stmt->fetchAll();

        // Top campaigns by open rate
        $topCampaigns = $db->query("
            SELECT name, total_sent, total_opened, total_clicked,
                   CASE WHEN total_sent > 0 THEN ROUND(total_opened * 100.0 / total_sent, 1) ELSE 0 END as open_rate,
                   CASE WHEN total_sent > 0 THEN ROUND(total_clicked * 100.0 / total_sent, 1) ELSE 0 END as click_rate
            FROM campaigns
            WHERE status = 'sent' AND total_sent > 0
            ORDER BY open_rate DESC LIMIT 5
        ")->fetchAll();

        // Contact sources
        $contactSources = $db->query("SELECT source, COUNT(*) as count FROM contacts GROUP BY source ORDER BY count DESC")->fetchAll();

        // Top tags
        $topTags = $db->query("SELECT t.name, t.color, COUNT(ct.contact_id) as count FROM tags t LEFT JOIN contact_tags ct ON t.id = ct.tag_id GROUP BY t.id ORDER BY count DESC LIMIT 10")->fetchAll();

        Router::json([
            'contact_growth' => $contactGrowth,
            'email_events' => $emailEvents,
            'form_submissions' => $formSubmissions,
            'top_campaigns' => $topCampaigns,
            'contact_sources' => $contactSources,
            'top_tags' => $topTags,
        ]);
    }

    public static function recentActivity(): void {
        $db = Database::getInstance();
        $limit = (int)($_GET['limit'] ?? 20);
        $stmt = $db->prepare("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?");
        $stmt->execute([$limit]);
        Router::json($stmt->fetchAll());
    }
}
