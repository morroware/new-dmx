<?php
class AutomationController {
    public static function index(): void {
        Router::json(Router::paginate(Database::getInstance(), "SELECT * FROM automations ORDER BY created_at DESC", [], (int)($_GET['page'] ?? 1)));
    }
    public static function show(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM automations WHERE id=?"); $stmt->execute([$p['id']]); $a = $stmt->fetch();
        if (!$a) { Router::json(['error'=>'Not found'], 404); return; }
        $a['trigger_config'] = json_decode($a['trigger_config'], true);
        $stmt = $db->prepare("SELECT * FROM automation_steps WHERE automation_id=? ORDER BY step_order"); $stmt->execute([$p['id']]);
        $a['steps'] = $stmt->fetchAll();
        foreach ($a['steps'] as &$s) $s['config'] = json_decode($s['config'], true);
        $stmt = $db->prepare("SELECT status,COUNT(*) as c FROM automation_queue WHERE automation_id=? GROUP BY status"); $stmt->execute([$p['id']]);
        $a['queue_stats'] = []; foreach ($stmt->fetchAll() as $r) $a['queue_stats'][$r['status']] = (int)$r['c'];
        Router::json($a);
    }
    public static function store(): void {
        $db = Database::getInstance(); $d = Router::body();
        if (empty($d['name'])||empty($d['trigger_type'])) { Router::json(['error'=>'Name and trigger required'], 422); return; }
        $db->prepare("INSERT INTO automations (name,description,trigger_type,trigger_config) VALUES (?,?,?,?)")
            ->execute([$d['name'],$d['description']??'',$d['trigger_type'],json_encode($d['trigger_config']??[])]);
        $aid = $db->lastInsertId();
        foreach ($d['steps'] ?? [] as $i => $s) {
            $db->prepare("INSERT INTO automation_steps (automation_id,step_order,type,config) VALUES (?,?,?,?)")
                ->execute([$aid,$i+1,$s['type'],json_encode($s['config']??[])]);
        }
        Router::json(['id'=>$aid], 201);
    }
    public static function update(array $p): void {
        $db = Database::getInstance(); $d = Router::body(); $f = []; $v = [];
        foreach (['name','description','trigger_type','status'] as $k) { if (isset($d[$k])) { $f[]="{$k}=?"; $v[]=$d[$k]; } }
        if (isset($d['trigger_config'])) { $f[]="trigger_config=?"; $v[]=json_encode($d['trigger_config']); }
        if ($f) { $f[]="updated_at=datetime('now')"; $v[]=$p['id']; $db->prepare("UPDATE automations SET ".implode(',',$f)." WHERE id=?")->execute($v); }
        if (isset($d['steps'])) {
            $db->prepare("DELETE FROM automation_steps WHERE automation_id=?")->execute([$p['id']]);
            foreach ($d['steps'] as $i => $s) {
                $db->prepare("INSERT INTO automation_steps (automation_id,step_order,type,config) VALUES (?,?,?,?)")
                    ->execute([$p['id'],$i+1,$s['type'],json_encode($s['config']??[])]);
            }
        }
        Router::json(['message'=>'Updated']);
    }
    public static function destroy(array $p): void { Database::getInstance()->prepare("DELETE FROM automations WHERE id=?")->execute([$p['id']]); Router::json(['message'=>'Deleted']); }
    public static function activate(array $p): void { Database::getInstance()->prepare("UPDATE automations SET status='active',updated_at=datetime('now') WHERE id=?")->execute([$p['id']]); Router::json(['message'=>'Activated']); }
    public static function pause(array $p): void { Database::getInstance()->prepare("UPDATE automations SET status='paused',updated_at=datetime('now') WHERE id=?")->execute([$p['id']]); Router::json(['message'=>'Paused']); }
    public static function triggerTypes(): void {
        Router::json([
            ['id'=>'contact_created','name'=>'Contact Created'],
            ['id'=>'contact_subscribed','name'=>'Contact Subscribed'],
            ['id'=>'form_submitted','name'=>'Form Submitted'],
            ['id'=>'tag_added','name'=>'Tag Added'],
            ['id'=>'list_joined','name'=>'Added to List'],
            ['id'=>'email_opened','name'=>'Email Opened'],
            ['id'=>'link_clicked','name'=>'Link Clicked'],
            ['id'=>'social_published','name'=>'Social Post Published'],
            ['id'=>'manual','name'=>'Manual Trigger'],
        ]);
    }
}
