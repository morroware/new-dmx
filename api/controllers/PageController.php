<?php
class PageController {
    public static function index(): void {
        Router::json(Router::paginate(Database::getInstance(), "SELECT lp.*,f.name as form_name FROM landing_pages lp LEFT JOIN forms f ON lp.form_id=f.id ORDER BY lp.created_at DESC", [], (int)($_GET['page'] ?? 1)));
    }
    public static function show(array $p): void {
        $stmt = Database::getInstance()->prepare("SELECT * FROM landing_pages WHERE id=?"); $stmt->execute([$p['id']]);
        $pg = $stmt->fetch(); if (!$pg) { Router::json(['error'=>'Not found'], 404); return; } Router::json($pg);
    }
    public static function store(): void {
        $d = Router::body(); if (empty($d['name'])) { Router::json(['error'=>'Name required'], 422); return; }
        $slug = $d['slug'] ?? preg_replace('/-+/','-',preg_replace('/[^a-z0-9-]/','-',strtolower(trim($d['name']))));
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT id FROM landing_pages WHERE slug=?"); $stmt->execute([$slug]);
        if ($stmt->fetch()) $slug .= '-'.substr(md5(uniqid()),0,6);
        $default = '<div style="max-width:800px;margin:0 auto;padding:60px 20px;text-align:center;background:#0f0f12;color:#f2f2f4;min-height:100vh;font-family:Arial,sans-serif;"><h1 style="font-size:36px;margin-bottom:16px;">'.htmlspecialchars($d['name']).'</h1><p style="font-size:18px;color:#a8a8b4;margin-bottom:40px;">Your landing page description.</p><div style="max-width:480px;margin:0 auto;">{{form}}</div></div>';
        $db->prepare("INSERT INTO landing_pages (name,slug,html_content,css_content,form_id,meta_title,meta_description,status) VALUES (?,?,?,?,?,?,?,?)")
            ->execute([$d['name'],$slug,$d['html_content']??$default,$d['css_content']??'',$d['form_id']??null,$d['meta_title']??$d['name'],$d['meta_description']??'',$d['status']??'draft']);
        Router::json(['id'=>$db->lastInsertId(),'slug'=>$slug], 201);
    }
    public static function update(array $p): void {
        $d = Router::body(); $f = []; $v = [];
        foreach (['name','slug','html_content','css_content','form_id','meta_title','meta_description','status'] as $k) { if (isset($d[$k])) { $f[]="{$k}=?"; $v[]=$d[$k]; } }
        if ($f) { $f[]="updated_at=datetime('now')"; $v[]=$p['id']; Database::getInstance()->prepare("UPDATE landing_pages SET ".implode(',',$f)." WHERE id=?")->execute($v); }
        Router::json(['message'=>'Updated']);
    }
    public static function destroy(array $p): void { Database::getInstance()->prepare("DELETE FROM landing_pages WHERE id=?")->execute([$p['id']]); Router::json(['message'=>'Deleted']); }
    public static function duplicate(array $p): void {
        $db = Database::getInstance(); $stmt = $db->prepare("SELECT * FROM landing_pages WHERE id=?"); $stmt->execute([$p['id']]); $pg = $stmt->fetch();
        if (!$pg) { Router::json(['error'=>'Not found'], 404); return; }
        $slug = $pg['slug'].'-'.substr(md5(uniqid()),0,6);
        $db->prepare("INSERT INTO landing_pages (name,slug,html_content,css_content,form_id,meta_title,meta_description,status) VALUES (?,?,?,?,?,?,?,'draft')")
            ->execute([$pg['name'].' (Copy)',$slug,$pg['html_content'],$pg['css_content'],$pg['form_id'],$pg['meta_title'],$pg['meta_description']]);
        Router::json(['id'=>$db->lastInsertId(),'slug'=>$slug], 201);
    }
    public static function render(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM landing_pages WHERE slug=? AND status='published'"); $stmt->execute([$p['slug']]); $pg = $stmt->fetch();
        if (!$pg) { http_response_code(404); echo '<h1>Not Found</h1>'; exit; }
        $db->prepare("UPDATE landing_pages SET total_views=total_views+1 WHERE id=?")->execute([$pg['id']]);
        $html = $pg['html_content'];
        if ($pg['form_id']) {
            ob_start(); FormController::embed(['id'=>$pg['form_id']]); $formHtml = ob_get_clean();
            $html = str_replace('{{form}}', $formHtml, $html);
        }
        header('Content-Type: text/html; charset=utf-8');
        echo "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>".htmlspecialchars($pg['meta_title']?:$pg['name'])."</title>";
        if ($pg['css_content']) echo "<style>{$pg['css_content']}</style>";
        echo "</head><body>{$html}</body></html>";
        exit;
    }
}
