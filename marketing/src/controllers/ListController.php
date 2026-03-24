<?php
class ListController {
    public static function index(): void {
        $db = Database::getInstance();
        $result = Router::paginate($db, "SELECT * FROM lists ORDER BY created_at DESC", [], (int)($_GET['page'] ?? 1));
        Router::json($result);
    }

    public static function show(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM lists WHERE id = ?");
        $stmt->execute([$params['id']]);
        $list = $stmt->fetch();
        if (!$list) { Router::json(['error' => 'Not found'], 404); return; }

        $list['segment_rules'] = json_decode($list['segment_rules'], true);

        // Get contacts in this list
        $page = (int)($_GET['page'] ?? 1);
        $contacts = Router::paginate($db,
            "SELECT c.* FROM contacts c JOIN list_contacts lc ON c.id = lc.contact_id WHERE lc.list_id = ? ORDER BY lc.added_at DESC",
            [$params['id']], $page
        );
        $list['contacts'] = $contacts;

        Router::json($list);
    }

    public static function store(): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        if (empty($data['name'])) { Router::json(['error' => 'Name is required'], 422); return; }

        $stmt = $db->prepare("INSERT INTO lists (name, description, type, segment_rules) VALUES (?, ?, ?, ?)");
        $stmt->execute([
            $data['name'],
            $data['description'] ?? '',
            $data['type'] ?? 'static',
            json_encode($data['segment_rules'] ?? []),
        ]);

        $id = $db->lastInsertId();

        // If dynamic segment, calculate members
        if (($data['type'] ?? 'static') === 'dynamic') {
            self::recalculateSegment($id);
        }

        ActivityLog::log('list_created', "List created: {$data['name']}", ['list_id' => $id]);
        Router::json(['id' => $id, 'message' => 'List created'], 201);
    }

    public static function update(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        $fields = [];
        $values = [];
        foreach (['name', 'description', 'type'] as $f) {
            if (isset($data[$f])) { $fields[] = "{$f} = ?"; $values[] = $data[$f]; }
        }
        if (isset($data['segment_rules'])) {
            $fields[] = "segment_rules = ?";
            $values[] = json_encode($data['segment_rules']);
        }

        if ($fields) {
            $fields[] = "updated_at = datetime('now')";
            $values[] = $params['id'];
            $db->prepare("UPDATE lists SET " . implode(', ', $fields) . " WHERE id = ?")->execute($values);
        }

        if (isset($data['segment_rules'])) {
            self::recalculateSegment($params['id']);
        }

        Router::json(['message' => 'List updated']);
    }

    public static function destroy(array $params): void {
        $db = Database::getInstance();
        $db->prepare("DELETE FROM lists WHERE id = ?")->execute([$params['id']]);
        Router::json(['message' => 'List deleted']);
    }

    public static function addContacts(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();
        $contactIds = $data['contact_ids'] ?? [];

        foreach ($contactIds as $cid) {
            $db->prepare("INSERT OR IGNORE INTO list_contacts (list_id, contact_id) VALUES (?, ?)")
                ->execute([$params['id'], $cid]);
        }

        // Update count
        $db->prepare("UPDATE lists SET contact_count = (SELECT COUNT(*) FROM list_contacts WHERE list_id = ?), updated_at = datetime('now') WHERE id = ?")
            ->execute([$params['id'], $params['id']]);

        Router::json(['message' => count($contactIds) . ' contacts added to list']);
    }

    public static function removeContacts(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();
        $contactIds = $data['contact_ids'] ?? [];

        $placeholders = implode(',', array_fill(0, count($contactIds), '?'));
        $db->prepare("DELETE FROM list_contacts WHERE list_id = ? AND contact_id IN ({$placeholders})")
            ->execute(array_merge([$params['id']], $contactIds));

        $db->prepare("UPDATE lists SET contact_count = (SELECT COUNT(*) FROM list_contacts WHERE list_id = ?), updated_at = datetime('now') WHERE id = ?")
            ->execute([$params['id'], $params['id']]);

        Router::json(['message' => count($contactIds) . ' contacts removed from list']);
    }

    public static function recalculateSegment(int $listId): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM lists WHERE id = ? AND type = 'dynamic'");
        $stmt->execute([$listId]);
        $list = $stmt->fetch();
        if (!$list) return;

        $rules = json_decode($list['segment_rules'], true);
        if (empty($rules)) return;

        // Build query from rules
        $where = [];
        $params = [];
        foreach ($rules as $rule) {
            $field = $rule['field'] ?? '';
            $operator = $rule['operator'] ?? 'equals';
            $value = $rule['value'] ?? '';

            $allowed = ['email', 'first_name', 'last_name', 'company', 'status', 'source', 'lead_score', 'created_at'];
            if (!in_array($field, $allowed)) continue;

            switch ($operator) {
                case 'equals':
                    $where[] = "{$field} = ?";
                    $params[] = $value;
                    break;
                case 'not_equals':
                    $where[] = "{$field} != ?";
                    $params[] = $value;
                    break;
                case 'contains':
                    $where[] = "{$field} LIKE ?";
                    $params[] = "%{$value}%";
                    break;
                case 'starts_with':
                    $where[] = "{$field} LIKE ?";
                    $params[] = "{$value}%";
                    break;
                case 'greater_than':
                    $where[] = "{$field} > ?";
                    $params[] = $value;
                    break;
                case 'less_than':
                    $where[] = "{$field} < ?";
                    $params[] = $value;
                    break;
                case 'is_empty':
                    $where[] = "({$field} IS NULL OR {$field} = '')";
                    break;
                case 'is_not_empty':
                    $where[] = "({$field} IS NOT NULL AND {$field} != '')";
                    break;
            }
        }

        if (empty($where)) return;

        $connector = $list['segment_rules_connector'] ?? 'AND';
        $whereStr = implode(" {$connector} ", $where);

        // Clear and repopulate
        $db->prepare("DELETE FROM list_contacts WHERE list_id = ?")->execute([$listId]);
        $db->prepare("INSERT INTO list_contacts (list_id, contact_id) SELECT ?, id FROM contacts WHERE {$whereStr}")
            ->execute(array_merge([$listId], $params));

        $db->prepare("UPDATE lists SET contact_count = (SELECT COUNT(*) FROM list_contacts WHERE list_id = ?), updated_at = datetime('now') WHERE id = ?")
            ->execute([$listId, $listId]);
    }
}
