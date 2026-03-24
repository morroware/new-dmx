<?php
class TemplateController {
    public static function index(): void {
        $cat = $_GET['category'] ?? ''; $w = ''; $p = [];
        if ($cat) { $w = 'WHERE category=?'; $p[] = $cat; }
        Router::json(Router::paginate(Database::getInstance(), "SELECT * FROM templates {$w} ORDER BY updated_at DESC", $p, (int)($_GET['page'] ?? 1)));
    }
    public static function show(array $p): void {
        $stmt = Database::getInstance()->prepare("SELECT * FROM templates WHERE id=?"); $stmt->execute([$p['id']]);
        $t = $stmt->fetch(); if (!$t) { Router::json(['error'=>'Not found'], 404); return; } Router::json($t);
    }
    public static function store(): void {
        $d = Router::body(); if (empty($d['name'])) { Router::json(['error'=>'Name required'], 422); return; }
        Database::getInstance()->prepare("INSERT INTO templates (name,subject,html_content,text_content,category) VALUES (?,?,?,?,?)")
            ->execute([$d['name'],$d['subject']??'',$d['html_content']??'',$d['text_content']??'',$d['category']??'general']);
        Router::json(['id'=>Database::getInstance()->lastInsertId()], 201);
    }
    public static function update(array $p): void {
        $d = Router::body(); $f = []; $v = [];
        foreach (['name','subject','html_content','text_content','category','is_active'] as $k) { if (isset($d[$k])) { $f[]="{$k}=?"; $v[]=$d[$k]; } }
        if ($f) { $f[]="updated_at=datetime('now')"; $v[]=$p['id']; Database::getInstance()->prepare("UPDATE templates SET ".implode(',',$f)." WHERE id=?")->execute($v); }
        Router::json(['message'=>'Updated']);
    }
    public static function destroy(array $p): void { Database::getInstance()->prepare("DELETE FROM templates WHERE id=?")->execute([$p['id']]); Router::json(['message'=>'Deleted']); }
    public static function duplicate(array $p): void {
        $db = Database::getInstance(); $stmt = $db->prepare("SELECT * FROM templates WHERE id=?"); $stmt->execute([$p['id']]); $t = $stmt->fetch();
        if (!$t) { Router::json(['error'=>'Not found'], 404); return; }
        $db->prepare("INSERT INTO templates (name,subject,html_content,text_content,category) VALUES (?,?,?,?,?)")
            ->execute([$t['name'].' (Copy)',$t['subject'],$t['html_content'],$t['text_content'],$t['category']]);
        Router::json(['id'=>$db->lastInsertId()], 201);
    }
    public static function starters(): void {
        Router::json([
            ['id'=>'blank','name'=>'Blank','category'=>'basic','html_content'=>'<div style="max-width:600px;margin:0 auto;font-family:Arial,sans-serif;padding:20px;">{{content}}<p style="text-align:center;color:#666;font-size:12px;margin-top:30px;"><a href="{{unsubscribe_url}}">Unsubscribe</a></p></div>'],
            ['id'=>'newsletter','name'=>'Newsletter','category'=>'newsletter','html_content'=>'<!DOCTYPE html><html><body style="margin:0;background:#111;"><div style="max-width:600px;margin:0 auto;background:#1a1a1f;color:#f2f2f4;font-family:Arial,sans-serif;"><div style="background:#FF6B35;padding:30px;text-align:center;"><h1 style="margin:0;color:#fff;">{{campaign_name}}</h1></div><div style="padding:30px;line-height:1.6;"><p>Hi {{first_name}},</p><p>Newsletter content here.</p></div><div style="padding:20px;text-align:center;color:#666;font-size:12px;"><a href="{{unsubscribe_url}}" style="color:#FF6B35;">Unsubscribe</a></div></div></body></html>'],
            ['id'=>'promo','name'=>'Promotional','category'=>'promotional','html_content'=>'<!DOCTYPE html><html><body style="margin:0;background:#111;"><div style="max-width:600px;margin:0 auto;background:#1a1a1f;color:#f2f2f4;font-family:Arial,sans-serif;"><div style="background:linear-gradient(135deg,#FF6B35,#ff8555);padding:40px;text-align:center;"><h1 style="margin:0 0 10px;color:#fff;font-size:28px;">Special Offer!</h1></div><div style="padding:30px;text-align:center;line-height:1.6;"><p>Hi {{first_name}},</p><a href="#" style="display:inline-block;background:#FF6B35;color:#fff;padding:15px 30px;border-radius:5px;text-decoration:none;font-weight:bold;">Shop Now</a></div><div style="padding:20px;text-align:center;color:#666;font-size:12px;"><a href="{{unsubscribe_url}}" style="color:#FF6B35;">Unsubscribe</a></div></div></body></html>'],
            ['id'=>'welcome','name'=>'Welcome','category'=>'transactional','html_content'=>'<!DOCTYPE html><html><body style="margin:0;background:#111;"><div style="max-width:600px;margin:0 auto;background:#1a1a1f;color:#f2f2f4;font-family:Arial,sans-serif;"><div style="background:#22C55E;padding:40px;text-align:center;"><h1 style="margin:0;color:#fff;">Welcome!</h1></div><div style="padding:30px;line-height:1.6;"><p>Hi {{first_name}},</p><p>Welcome aboard! We\'re thrilled to have you.</p></div><div style="padding:20px;text-align:center;color:#666;font-size:12px;"><a href="{{unsubscribe_url}}" style="color:#22C55E;">Unsubscribe</a></div></div></body></html>'],
            ['id'=>'minimal','name'=>'Minimal','category'=>'basic','html_content'=>'<!DOCTYPE html><html><body style="margin:0;padding:40px;background:#111;color:#f2f2f4;font-family:Georgia,serif;"><div style="max-width:600px;margin:0 auto;line-height:1.8;"><p>Hi {{first_name}},</p><p>Your message here.</p><p>Best,<br>Your Name</p><hr style="border:none;border-top:1px solid #333;margin:30px 0;"><p style="font-size:12px;color:#666;"><a href="{{unsubscribe_url}}" style="color:#666;">Unsubscribe</a></p></div></body></html>'],
        ]);
    }
}
