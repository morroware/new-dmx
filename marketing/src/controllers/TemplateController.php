<?php
class TemplateController {
    public static function index(): void {
        $db = Database::getInstance();
        $page = (int)($_GET['page'] ?? 1);
        $category = $_GET['category'] ?? '';

        $where = '';
        $params = [];
        if ($category) { $where = 'WHERE category = ?'; $params[] = $category; }

        $result = Router::paginate($db, "SELECT * FROM templates {$where} ORDER BY updated_at DESC", $params, $page);
        Router::json($result);
    }

    public static function show(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM templates WHERE id = ?");
        $stmt->execute([$params['id']]);
        $template = $stmt->fetch();
        if (!$template) { Router::json(['error' => 'Template not found'], 404); return; }
        Router::json($template);
    }

    public static function store(): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        if (empty($data['name'])) { Router::json(['error' => 'Template name is required'], 422); return; }

        $stmt = $db->prepare("INSERT INTO templates (name, subject, html_content, text_content, category) VALUES (?, ?, ?, ?, ?)");
        $stmt->execute([
            $data['name'],
            $data['subject'] ?? '',
            $data['html_content'] ?? '',
            $data['text_content'] ?? '',
            $data['category'] ?? 'general',
        ]);

        $id = $db->lastInsertId();
        ActivityLog::log('template_created', "Template created: {$data['name']}", ['template_id' => $id]);
        Router::json(['id' => $id, 'message' => 'Template created'], 201);
    }

    public static function update(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        $fields = ['name', 'subject', 'html_content', 'text_content', 'category', 'is_active'];
        $updates = [];
        $values = [];
        foreach ($fields as $f) {
            if (isset($data[$f])) { $updates[] = "{$f} = ?"; $values[] = $data[$f]; }
        }

        if ($updates) {
            $updates[] = "updated_at = datetime('now')";
            $values[] = $params['id'];
            $db->prepare("UPDATE templates SET " . implode(', ', $updates) . " WHERE id = ?")->execute($values);
        }

        Router::json(['message' => 'Template updated']);
    }

    public static function destroy(array $params): void {
        $db = Database::getInstance();
        $db->prepare("DELETE FROM templates WHERE id = ?")->execute([$params['id']]);
        Router::json(['message' => 'Template deleted']);
    }

    public static function duplicate(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM templates WHERE id = ?");
        $stmt->execute([$params['id']]);
        $template = $stmt->fetch();
        if (!$template) { Router::json(['error' => 'Not found'], 404); return; }

        $stmt = $db->prepare("INSERT INTO templates (name, subject, html_content, text_content, category) VALUES (?, ?, ?, ?, ?)");
        $stmt->execute([$template['name'] . ' (Copy)', $template['subject'], $template['html_content'], $template['text_content'], $template['category']]);

        Router::json(['id' => $db->lastInsertId(), 'message' => 'Template duplicated'], 201);
    }

    public static function getStarters(): void {
        $starters = [
            [
                'id' => 'blank',
                'name' => 'Blank Template',
                'category' => 'basic',
                'html_content' => '<div style="max-width:600px;margin:0 auto;font-family:Arial,sans-serif;"><div style="padding:20px;">{{content}}</div><div style="padding:20px;text-align:center;color:#666;font-size:12px;"><p>{{company_name}} | {{company_address}}</p><p><a href="{{unsubscribe_url}}">Unsubscribe</a></p></div></div>',
            ],
            [
                'id' => 'newsletter',
                'name' => 'Newsletter',
                'category' => 'newsletter',
                'html_content' => '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;padding:0;background:#f4f4f4;"><div style="max-width:600px;margin:0 auto;background:#ffffff;"><div style="background:#6366f1;color:#fff;padding:30px;text-align:center;"><h1 style="margin:0;font-family:Arial,sans-serif;">{{campaign_name}}</h1></div><div style="padding:30px;font-family:Arial,sans-serif;color:#333;line-height:1.6;"><p>Hi {{first_name}},</p><p>Your newsletter content goes here.</p></div><div style="background:#f8f9fa;padding:20px;text-align:center;font-family:Arial,sans-serif;color:#666;font-size:12px;"><p>&copy; {{current_year}} Your Company</p><p><a href="{{unsubscribe_url}}" style="color:#6366f1;">Unsubscribe</a></p></div></div></body></html>',
            ],
            [
                'id' => 'promotion',
                'name' => 'Promotional',
                'category' => 'promotional',
                'html_content' => '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;padding:0;background:#f4f4f4;"><div style="max-width:600px;margin:0 auto;background:#ffffff;"><div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:40px;text-align:center;"><h1 style="margin:0 0 10px;font-family:Arial,sans-serif;font-size:28px;">Special Offer!</h1><p style="margin:0;font-size:18px;opacity:0.9;">Don\'t miss out on this deal</p></div><div style="padding:30px;font-family:Arial,sans-serif;color:#333;line-height:1.6;text-align:center;"><p>Hi {{first_name}},</p><p style="font-size:18px;">Your promotional content goes here.</p><a href="#" style="display:inline-block;background:#6366f1;color:#fff;padding:15px 30px;border-radius:5px;text-decoration:none;font-weight:bold;margin:20px 0;">Shop Now</a></div><div style="background:#f8f9fa;padding:20px;text-align:center;font-family:Arial,sans-serif;color:#666;font-size:12px;"><p>&copy; {{current_year}} Your Company</p><p><a href="{{unsubscribe_url}}" style="color:#6366f1;">Unsubscribe</a></p></div></div></body></html>',
            ],
            [
                'id' => 'welcome',
                'name' => 'Welcome Email',
                'category' => 'transactional',
                'html_content' => '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;padding:0;background:#f4f4f4;"><div style="max-width:600px;margin:0 auto;background:#ffffff;"><div style="background:#10b981;color:#fff;padding:40px;text-align:center;"><h1 style="margin:0;font-family:Arial,sans-serif;">Welcome!</h1></div><div style="padding:30px;font-family:Arial,sans-serif;color:#333;line-height:1.6;"><p>Hi {{first_name}},</p><p>Welcome aboard! We\'re thrilled to have you join us.</p><p>Here\'s what you can expect:</p><ul><li>Regular updates and insights</li><li>Exclusive offers and promotions</li><li>Helpful tips and resources</li></ul><p>If you have any questions, just reply to this email.</p><p>Best regards,<br>The Team</p></div><div style="background:#f8f9fa;padding:20px;text-align:center;font-family:Arial,sans-serif;color:#666;font-size:12px;"><p>&copy; {{current_year}} Your Company</p><p><a href="{{unsubscribe_url}}" style="color:#10b981;">Unsubscribe</a></p></div></div></body></html>',
            ],
            [
                'id' => 'announcement',
                'name' => 'Announcement',
                'category' => 'general',
                'html_content' => '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;padding:0;background:#f4f4f4;"><div style="max-width:600px;margin:0 auto;background:#ffffff;"><div style="background:#1e293b;color:#fff;padding:40px;text-align:center;"><h1 style="margin:0 0 10px;font-family:Arial,sans-serif;">Announcement</h1><p style="margin:0;opacity:0.8;">Important Update</p></div><div style="padding:30px;font-family:Arial,sans-serif;color:#333;line-height:1.6;"><p>Hi {{first_name}},</p><p>We have an important announcement to share with you.</p><p>Your announcement content goes here.</p></div><div style="background:#f8f9fa;padding:20px;text-align:center;font-family:Arial,sans-serif;color:#666;font-size:12px;"><p>&copy; {{current_year}} Your Company</p><p><a href="{{unsubscribe_url}}" style="color:#6366f1;">Unsubscribe</a></p></div></div></body></html>',
            ],
            [
                'id' => 'minimal',
                'name' => 'Minimal Text',
                'category' => 'basic',
                'html_content' => '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="margin:0;padding:0;background:#ffffff;"><div style="max-width:600px;margin:0 auto;padding:40px 20px;font-family:Georgia,serif;color:#333;line-height:1.8;"><p>Hi {{first_name}},</p><p>Your message here.</p><p>Best,<br>Your Name</p><hr style="border:none;border-top:1px solid #eee;margin:30px 0;"><p style="font-size:12px;color:#999;"><a href="{{unsubscribe_url}}" style="color:#999;">Unsubscribe</a></p></div></body></html>',
            ],
        ];

        Router::json($starters);
    }
}
