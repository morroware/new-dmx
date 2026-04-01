<?php
class ListController {
    public static function index(): void {
        $result = Router::paginate(Database::getInstance(), "SELECT * FROM lists ORDER BY created_at DESC", [], (int)($_GET['page'] ?? 1));
        Router::json($result);
    }
    public static function show(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM lists WHERE id=?"); $stmt->execute([$p['id']]); $l = $stmt->fetch();
        if (!$l) { Router::json(['error' => 'Not found'], 404); return; }
        $l['segment_rules'] = json_decode($l['segment_rules'], true);
        $l['contacts'] = Router::paginate($db, "SELECT c.* FROM contacts c JOIN list_contacts lc ON c.id=lc.contact_id WHERE lc.list_id=? ORDER BY lc.added_at DESC", [$p['id']], (int)($_GET['page'] ?? 1));
        Router::json($l);
    }
    public static function store(): void {
        $db = Database::getInstance(); $d = Router::body();
        if (empty($d['name'])) { Router::json(['error' => 'Name required'], 422); return; }
        $db->prepare("INSERT INTO lists (name,description,type,segment_rules) VALUES (?,?,?,?)")
            ->execute([$d['name'],$d['description']??'',$d['type']??'static',json_encode($d['segment_rules']??[])]);
        Router::json(['id' => $db->lastInsertId()], 201);
    }
    public static function update(array $p): void {
        $db = Database::getInstance(); $d = Router::body(); $f = []; $v = [];
        foreach (['name','description','type'] as $k) { if (isset($d[$k])) { $f[] = "{$k}=?"; $v[] = $d[$k]; } }
        if (isset($d['segment_rules'])) { $f[] = "segment_rules=?"; $v[] = json_encode($d['segment_rules']); }
        if ($f) { $f[] = "updated_at=datetime('now')"; $v[] = $p['id']; $db->prepare("UPDATE lists SET ".implode(',',$f)." WHERE id=?")->execute($v); }
        Router::json(['message' => 'Updated']);
    }
    public static function destroy(array $p): void { Database::getInstance()->prepare("DELETE FROM lists WHERE id=?")->execute([$p['id']]); Router::json(['message' => 'Deleted']); }
    public static function addContacts(array $p): void {
        $db = Database::getInstance(); $ids = Router::body()['contact_ids'] ?? [];
        foreach ($ids as $id) $db->prepare("INSERT OR IGNORE INTO list_contacts (list_id,contact_id) VALUES (?,?)")->execute([$p['id'],$id]);
        $db->prepare("UPDATE lists SET contact_count=(SELECT COUNT(*) FROM list_contacts WHERE list_id=?) WHERE id=?")->execute([$p['id'],$p['id']]);
        Router::json(['message' => count($ids).' added']);
    }
    public static function removeContacts(array $p): void {
        $db = Database::getInstance(); $ids = Router::body()['contact_ids'] ?? [];
        $ph = implode(',',array_fill(0,count($ids),'?'));
        $db->prepare("DELETE FROM list_contacts WHERE list_id=? AND contact_id IN ({$ph})")->execute(array_merge([$p['id']],$ids));
        $db->prepare("UPDATE lists SET contact_count=(SELECT COUNT(*) FROM list_contacts WHERE list_id=?) WHERE id=?")->execute([$p['id'],$p['id']]);
        Router::json(['message' => count($ids).' removed']);
    }
}
