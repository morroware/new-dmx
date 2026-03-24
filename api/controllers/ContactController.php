<?php
class ContactController {
    public static function index(): void {
        $db = Database::getInstance();
        $page = (int)($_GET['page'] ?? 1);
        $search = $_GET['search'] ?? '';
        $status = $_GET['status'] ?? '';
        $tag = $_GET['tag'] ?? '';

        $where = []; $params = [];
        if ($search) {
            $where[] = "(c.email LIKE ? OR c.first_name LIKE ? OR c.last_name LIKE ? OR c.company LIKE ?)";
            $s = "%{$search}%"; $params = [$s,$s,$s,$s];
        }
        if ($status) { $where[] = "c.status = ?"; $params[] = $status; }
        if ($tag) { $where[] = "c.id IN (SELECT contact_id FROM contact_tags ct JOIN tags t ON ct.tag_id=t.id WHERE t.name=?)"; $params[] = $tag; }

        $w = $where ? 'WHERE ' . implode(' AND ', $where) : '';
        $sort = $_GET['sort'] ?? 'created_at';
        $order = strtoupper($_GET['order'] ?? 'DESC') === 'ASC' ? 'ASC' : 'DESC';
        $allowed = ['email','first_name','last_name','lead_score','created_at'];
        if (!in_array($sort, $allowed)) $sort = 'created_at';

        $result = Router::paginate($db,
            "SELECT c.*, GROUP_CONCAT(t.name) as tag_names FROM contacts c LEFT JOIN contact_tags ct ON c.id=ct.contact_id LEFT JOIN tags t ON ct.tag_id=t.id {$w} GROUP BY c.id ORDER BY c.{$sort} {$order}",
            $params, $page
        );
        foreach ($result['items'] as &$item) {
            $item['tags'] = $item['tag_names'] ? explode(',', $item['tag_names']) : [];
            unset($item['tag_names']);
        }
        Router::json($result);
    }

    public static function show(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM contacts WHERE id = ?"); $stmt->execute([$p['id']]);
        $c = $stmt->fetch();
        if (!$c) { Router::json(['error' => 'Not found'], 404); return; }
        $c['custom_fields'] = json_decode($c['custom_fields'] ?? '{}', true);
        $stmt = $db->prepare("SELECT t.* FROM tags t JOIN contact_tags ct ON t.id=ct.tag_id WHERE ct.contact_id=?");
        $stmt->execute([$p['id']]); $c['tags'] = $stmt->fetchAll();
        $stmt = $db->prepare("SELECT l.id,l.name FROM lists l JOIN list_contacts lc ON l.id=lc.list_id WHERE lc.contact_id=?");
        $stmt->execute([$p['id']]); $c['lists'] = $stmt->fetchAll();
        $stmt = $db->prepare("SELECT * FROM email_events WHERE contact_id=? ORDER BY created_at DESC LIMIT 20");
        $stmt->execute([$p['id']]); $c['recent_events'] = $stmt->fetchAll();
        Router::json($c);
    }

    public static function store(): void {
        $db = Database::getInstance();
        $d = Router::body();
        if (empty($d['email']) || !filter_var($d['email'], FILTER_VALIDATE_EMAIL)) {
            Router::json(['error' => 'Valid email required'], 422); return;
        }
        $stmt = $db->prepare("SELECT id FROM contacts WHERE email=?"); $stmt->execute([$d['email']]);
        if ($stmt->fetch()) { Router::json(['error' => 'Email already exists'], 409); return; }

        $db->prepare("INSERT INTO contacts (email,first_name,last_name,company,phone,status,source,custom_fields,notes) VALUES (?,?,?,?,?,?,?,?,?)")
            ->execute([$d['email'], $d['first_name']??'', $d['last_name']??'', $d['company']??'', $d['phone']??'', $d['status']??'subscribed', $d['source']??'manual', json_encode($d['custom_fields']??[]), $d['notes']??'']);
        $id = $db->lastInsertId();
        if (!empty($d['tags'])) self::applyTags($id, $d['tags']);
        logActivity('contact_created', "Contact created: {$d['email']}");
        Router::json(['id' => $id, 'message' => 'Contact created'], 201);
    }

    public static function update(array $p): void {
        $db = Database::getInstance(); $d = Router::body();
        $fields = []; $vals = [];
        foreach (['email','first_name','last_name','company','phone','status','notes','lead_score'] as $f) {
            if (isset($d[$f])) { $fields[] = "{$f}=?"; $vals[] = $d[$f]; }
        }
        if (isset($d['custom_fields'])) { $fields[] = "custom_fields=?"; $vals[] = json_encode($d['custom_fields']); }
        if ($fields) { $fields[] = "updated_at=datetime('now')"; $vals[] = $p['id'];
            $db->prepare("UPDATE contacts SET ".implode(',',$fields)." WHERE id=?")->execute($vals);
        }
        if (isset($d['tags'])) {
            $db->prepare("DELETE FROM contact_tags WHERE contact_id=?")->execute([$p['id']]);
            self::applyTags($p['id'], $d['tags']);
        }
        Router::json(['message' => 'Contact updated']);
    }

    public static function destroy(array $p): void {
        Database::getInstance()->prepare("DELETE FROM contacts WHERE id=?")->execute([$p['id']]);
        Router::json(['message' => 'Contact deleted']);
    }

    public static function bulk(): void {
        $db = Database::getInstance(); $d = Router::body();
        $ids = $d['ids'] ?? []; $action = $d['action'] ?? '';
        if (!$ids) { Router::json(['error' => 'No contacts selected'], 422); return; }
        $ph = implode(',', array_fill(0, count($ids), '?'));
        match ($action) {
            'delete' => $db->prepare("DELETE FROM contacts WHERE id IN ({$ph})")->execute($ids),
            'subscribe' => $db->prepare("UPDATE contacts SET status='subscribed',updated_at=datetime('now') WHERE id IN ({$ph})")->execute($ids),
            'unsubscribe' => $db->prepare("UPDATE contacts SET status='unsubscribed',unsubscribed_at=datetime('now'),updated_at=datetime('now') WHERE id IN ({$ph})")->execute($ids),
            'add_tag' => !empty($d['tag']) ? array_map(fn($id) => self::applyTags($id, [$d['tag']]), $ids) : null,
            'add_to_list' => !empty($d['list_id']) ? array_map(fn($id) => $db->prepare("INSERT OR IGNORE INTO list_contacts (list_id,contact_id) VALUES (?,?)")->execute([$d['list_id'],$id]), $ids) : null,
            default => null,
        };
        logActivity('bulk_action', "Bulk {$action} on ".count($ids)." contacts");
        Router::json(['message' => "Applied '{$action}' to ".count($ids)." contacts"]);
    }

    public static function import(): void {
        $db = Database::getInstance();
        if (!empty($_FILES['file'])) {
            $contacts = [];
            if (($h = fopen($_FILES['file']['tmp_name'], 'r')) !== false) {
                $hdrs = array_map('strtolower', array_map('trim', fgetcsv($h)));
                while (($row = fgetcsv($h)) !== false) $contacts[] = array_combine($hdrs, array_pad($row, count($hdrs), ''));
                fclose($h);
            }
        } else {
            $contacts = Router::body()['contacts'] ?? [];
        }

        $imported = 0; $skipped = 0;
        $listId = $_POST['list_id'] ?? Router::body()['list_id'] ?? null;
        $db->beginTransaction();
        try {
            foreach ($contacts as $c) {
                $email = trim($c['email'] ?? '');
                if (!$email || !filter_var($email, FILTER_VALIDATE_EMAIL)) { $skipped++; continue; }
                $stmt = $db->prepare("SELECT id FROM contacts WHERE email=?"); $stmt->execute([$email]);
                if ($stmt->fetch()) { $skipped++; continue; }
                $db->prepare("INSERT INTO contacts (email,first_name,last_name,company,phone,source) VALUES (?,?,?,?,?,'import')")
                    ->execute([$email, $c['first_name']??'', $c['last_name']??'', $c['company']??'', $c['phone']??'']);
                $cid = $db->lastInsertId();
                if ($listId) $db->prepare("INSERT OR IGNORE INTO list_contacts (list_id,contact_id) VALUES (?,?)")->execute([$listId,$cid]);
                $imported++;
            }
            $db->commit();
            Router::json(['imported' => $imported, 'skipped' => $skipped]);
        } catch (\Exception $e) { $db->rollBack(); Router::json(['error' => $e->getMessage()], 500); }
    }

    public static function export(): void {
        $db = Database::getInstance();
        $stmt = $db->query("SELECT email,first_name,last_name,company,phone,status,lead_score,source,created_at FROM contacts ORDER BY created_at DESC");
        header('Content-Type: text/csv');
        header('Content-Disposition: attachment; filename="contacts_'.date('Y-m-d').'.csv"');
        $out = fopen('php://output', 'w');
        fputcsv($out, ['email','first_name','last_name','company','phone','status','lead_score','source','created_at']);
        foreach ($stmt->fetchAll() as $c) fputcsv($out, $c);
        fclose($out); exit;
    }

    private static function applyTags(int $cid, array $tags): void {
        $db = Database::getInstance();
        foreach ($tags as $name) {
            $name = trim($name); if (!$name) continue;
            $db->prepare("INSERT OR IGNORE INTO tags (name) VALUES (?)")->execute([$name]);
            $t = $db->prepare("SELECT id FROM tags WHERE name=?"); $t->execute([$name]); $tag = $t->fetch();
            if ($tag) $db->prepare("INSERT OR IGNORE INTO contact_tags (contact_id,tag_id) VALUES (?,?)")->execute([$cid,$tag['id']]);
        }
    }
}
