<?php
class ContactController {
    public static function index(): void {
        $db = Database::getInstance();
        $page = (int)($_GET['page'] ?? 1);
        $perPage = (int)($_GET['per_page'] ?? PER_PAGE_DEFAULT);
        $search = $_GET['search'] ?? '';
        $status = $_GET['status'] ?? '';
        $tag = $_GET['tag'] ?? '';
        $listId = $_GET['list_id'] ?? '';
        $sort = $_GET['sort'] ?? 'created_at';
        $order = strtoupper($_GET['order'] ?? 'DESC') === 'ASC' ? 'ASC' : 'DESC';

        $allowedSorts = ['email', 'first_name', 'last_name', 'company', 'lead_score', 'created_at', 'updated_at'];
        if (!in_array($sort, $allowedSorts)) $sort = 'created_at';

        $where = [];
        $params = [];

        if ($search) {
            $where[] = "(c.email LIKE ? OR c.first_name LIKE ? OR c.last_name LIKE ? OR c.company LIKE ?)";
            $s = "%{$search}%";
            $params = array_merge($params, [$s, $s, $s, $s]);
        }
        if ($status) {
            $where[] = "c.status = ?";
            $params[] = $status;
        }
        if ($tag) {
            $where[] = "c.id IN (SELECT contact_id FROM contact_tags ct JOIN tags t ON ct.tag_id = t.id WHERE t.name = ?)";
            $params[] = $tag;
        }
        if ($listId) {
            $where[] = "c.id IN (SELECT contact_id FROM list_contacts WHERE list_id = ?)";
            $params[] = $listId;
        }

        $whereStr = $where ? 'WHERE ' . implode(' AND ', $where) : '';

        $query = "SELECT c.*, GROUP_CONCAT(t.name, ',') as tag_names
                  FROM contacts c
                  LEFT JOIN contact_tags ct ON c.id = ct.contact_id
                  LEFT JOIN tags t ON ct.tag_id = t.id
                  {$whereStr}
                  GROUP BY c.id
                  ORDER BY c.{$sort} {$order}";

        $result = Router::paginate($db, $query, $params, $page, $perPage);
        foreach ($result['items'] as &$item) {
            $item['tags'] = $item['tag_names'] ? explode(',', $item['tag_names']) : [];
            unset($item['tag_names']);
            $item['custom_fields'] = json_decode($item['custom_fields'] ?? '{}', true);
        }

        Router::json($result);
    }

    public static function show(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM contacts WHERE id = ?");
        $stmt->execute([$params['id']]);
        $contact = $stmt->fetch();
        if (!$contact) { Router::json(['error' => 'Contact not found'], 404); return; }

        $contact['custom_fields'] = json_decode($contact['custom_fields'] ?? '{}', true);

        // Get tags
        $stmt = $db->prepare("SELECT t.* FROM tags t JOIN contact_tags ct ON t.id = ct.tag_id WHERE ct.contact_id = ?");
        $stmt->execute([$params['id']]);
        $contact['tags'] = $stmt->fetchAll();

        // Get lists
        $stmt = $db->prepare("SELECT l.id, l.name FROM lists l JOIN list_contacts lc ON l.id = lc.list_id WHERE lc.contact_id = ?");
        $stmt->execute([$params['id']]);
        $contact['lists'] = $stmt->fetchAll();

        // Recent activity
        $stmt = $db->prepare("SELECT * FROM email_events WHERE contact_id = ? ORDER BY created_at DESC LIMIT 20");
        $stmt->execute([$params['id']]);
        $contact['recent_events'] = $stmt->fetchAll();

        Router::json($contact);
    }

    public static function store(): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        if (empty($data['email']) || !filter_var($data['email'], FILTER_VALIDATE_EMAIL)) {
            Router::json(['error' => 'Valid email is required'], 422);
            return;
        }

        // Check duplicate
        $stmt = $db->prepare("SELECT id FROM contacts WHERE email = ?");
        $stmt->execute([$data['email']]);
        if ($stmt->fetch()) {
            Router::json(['error' => 'Contact with this email already exists'], 409);
            return;
        }

        $stmt = $db->prepare("INSERT INTO contacts (email, first_name, last_name, company, phone, status, source, custom_fields, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)");
        $stmt->execute([
            $data['email'],
            $data['first_name'] ?? '',
            $data['last_name'] ?? '',
            $data['company'] ?? '',
            $data['phone'] ?? '',
            $data['status'] ?? 'subscribed',
            $data['source'] ?? 'manual',
            json_encode($data['custom_fields'] ?? []),
            $data['notes'] ?? '',
        ]);

        $contactId = $db->lastInsertId();

        // Apply tags
        if (!empty($data['tags'])) {
            self::applyTags($contactId, $data['tags']);
        }

        // Add to lists
        if (!empty($data['list_ids'])) {
            foreach ($data['list_ids'] as $listId) {
                $db->prepare("INSERT OR IGNORE INTO list_contacts (list_id, contact_id) VALUES (?, ?)")
                    ->execute([$listId, $contactId]);
            }
            self::updateListCounts($data['list_ids']);
        }

        ActivityLog::log('contact_created', "Contact created: {$data['email']}", ['contact_id' => $contactId]);

        Router::json(['id' => $contactId, 'message' => 'Contact created'], 201);
    }

    public static function update(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        $stmt = $db->prepare("SELECT * FROM contacts WHERE id = ?");
        $stmt->execute([$params['id']]);
        if (!$stmt->fetch()) { Router::json(['error' => 'Contact not found'], 404); return; }

        if (isset($data['email']) && !filter_var($data['email'], FILTER_VALIDATE_EMAIL)) {
            Router::json(['error' => 'Valid email is required'], 422);
            return;
        }

        $fields = ['email', 'first_name', 'last_name', 'company', 'phone', 'status', 'notes', 'lead_score'];
        $updates = [];
        $values = [];
        foreach ($fields as $field) {
            if (isset($data[$field])) {
                $updates[] = "{$field} = ?";
                $values[] = $data[$field];
            }
        }
        if (isset($data['custom_fields'])) {
            $updates[] = "custom_fields = ?";
            $values[] = json_encode($data['custom_fields']);
        }

        if ($updates) {
            $updates[] = "updated_at = datetime('now')";
            $values[] = $params['id'];
            $db->prepare("UPDATE contacts SET " . implode(', ', $updates) . " WHERE id = ?")->execute($values);
        }

        if (isset($data['tags'])) {
            $db->prepare("DELETE FROM contact_tags WHERE contact_id = ?")->execute([$params['id']]);
            self::applyTags($params['id'], $data['tags']);
        }

        Router::json(['message' => 'Contact updated']);
    }

    public static function destroy(array $params): void {
        $db = Database::getInstance();
        $db->prepare("DELETE FROM contacts WHERE id = ?")->execute([$params['id']]);
        ActivityLog::log('contact_deleted', "Contact deleted: ID {$params['id']}");
        Router::json(['message' => 'Contact deleted']);
    }

    public static function bulkAction(): void {
        $db = Database::getInstance();
        $data = Router::getBody();
        $ids = $data['ids'] ?? [];
        $action = $data['action'] ?? '';

        if (empty($ids)) { Router::json(['error' => 'No contacts selected'], 422); return; }

        $placeholders = implode(',', array_fill(0, count($ids), '?'));

        switch ($action) {
            case 'delete':
                $db->prepare("DELETE FROM contacts WHERE id IN ({$placeholders})")->execute($ids);
                break;
            case 'subscribe':
                $db->prepare("UPDATE contacts SET status = 'subscribed', updated_at = datetime('now') WHERE id IN ({$placeholders})")->execute($ids);
                break;
            case 'unsubscribe':
                $db->prepare("UPDATE contacts SET status = 'unsubscribed', unsubscribed_at = datetime('now'), updated_at = datetime('now') WHERE id IN ({$placeholders})")->execute($ids);
                break;
            case 'add_tag':
                if (!empty($data['tag'])) {
                    foreach ($ids as $id) self::applyTags($id, [$data['tag']]);
                }
                break;
            case 'remove_tag':
                if (!empty($data['tag_id'])) {
                    foreach ($ids as $id) {
                        $db->prepare("DELETE FROM contact_tags WHERE contact_id = ? AND tag_id = ?")->execute([$id, $data['tag_id']]);
                    }
                }
                break;
            case 'add_to_list':
                if (!empty($data['list_id'])) {
                    foreach ($ids as $id) {
                        $db->prepare("INSERT OR IGNORE INTO list_contacts (list_id, contact_id) VALUES (?, ?)")->execute([$data['list_id'], $id]);
                    }
                    self::updateListCounts([$data['list_id']]);
                }
                break;
            default:
                Router::json(['error' => 'Invalid action'], 422);
                return;
        }

        ActivityLog::log('bulk_action', "Bulk {$action} on " . count($ids) . " contacts");
        Router::json(['message' => "Bulk action '{$action}' applied to " . count($ids) . " contacts"]);
    }

    public static function import(): void {
        $db = Database::getInstance();

        if (empty($_FILES['file'])) {
            // Try JSON body import
            $data = Router::getBody();
            $contacts = $data['contacts'] ?? [];
        } else {
            $file = $_FILES['file']['tmp_name'];
            $contacts = [];
            if (($handle = fopen($file, 'r')) !== false) {
                $headers = fgetcsv($handle);
                $headers = array_map('strtolower', array_map('trim', $headers));
                while (($row = fgetcsv($handle)) !== false) {
                    $contact = array_combine($headers, array_pad($row, count($headers), ''));
                    $contacts[] = $contact;
                }
                fclose($handle);
            }
        }

        $imported = 0;
        $skipped = 0;
        $errors = [];
        $listId = $_POST['list_id'] ?? $data['list_id'] ?? null;

        $db->beginTransaction();
        try {
            foreach ($contacts as $i => $contact) {
                $email = trim($contact['email'] ?? '');
                if (!$email || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
                    $skipped++;
                    continue;
                }

                $stmt = $db->prepare("SELECT id FROM contacts WHERE email = ?");
                $stmt->execute([$email]);
                $existing = $stmt->fetch();

                if ($existing) {
                    // Update existing
                    $updates = [];
                    $values = [];
                    foreach (['first_name', 'last_name', 'company', 'phone'] as $f) {
                        if (!empty($contact[$f])) {
                            $updates[] = "{$f} = ?";
                            $values[] = $contact[$f];
                        }
                    }
                    if ($updates) {
                        $values[] = $existing['id'];
                        $db->prepare("UPDATE contacts SET " . implode(', ', $updates) . ", updated_at = datetime('now') WHERE id = ?")->execute($values);
                    }
                    $contactId = $existing['id'];
                    $skipped++;
                } else {
                    $stmt = $db->prepare("INSERT INTO contacts (email, first_name, last_name, company, phone, source) VALUES (?, ?, ?, ?, ?, 'import')");
                    $stmt->execute([
                        $email,
                        $contact['first_name'] ?? '',
                        $contact['last_name'] ?? '',
                        $contact['company'] ?? '',
                        $contact['phone'] ?? '',
                    ]);
                    $contactId = $db->lastInsertId();
                    $imported++;
                }

                if ($listId) {
                    $db->prepare("INSERT OR IGNORE INTO list_contacts (list_id, contact_id) VALUES (?, ?)")->execute([$listId, $contactId]);
                }

                if (!empty($contact['tags'])) {
                    $tags = is_array($contact['tags']) ? $contact['tags'] : explode(';', $contact['tags']);
                    self::applyTags($contactId, $tags);
                }
            }
            $db->commit();

            if ($listId) self::updateListCounts([$listId]);

            ActivityLog::log('contacts_imported', "Imported {$imported} contacts, {$skipped} skipped");
            Router::json(['imported' => $imported, 'skipped' => $skipped, 'errors' => $errors]);
        } catch (Exception $e) {
            $db->rollBack();
            Router::json(['error' => 'Import failed: ' . $e->getMessage()], 500);
        }
    }

    public static function export(): void {
        $db = Database::getInstance();
        $listId = $_GET['list_id'] ?? '';
        $status = $_GET['status'] ?? '';

        $where = [];
        $params = [];
        if ($status) { $where[] = "c.status = ?"; $params[] = $status; }
        if ($listId) { $where[] = "c.id IN (SELECT contact_id FROM list_contacts WHERE list_id = ?)"; $params[] = $listId; }
        $whereStr = $where ? 'WHERE ' . implode(' AND ', $where) : '';

        $stmt = $db->prepare("SELECT c.email, c.first_name, c.last_name, c.company, c.phone, c.status, c.lead_score, c.source, c.created_at FROM contacts c {$whereStr} ORDER BY c.created_at DESC");
        $stmt->execute($params);
        $contacts = $stmt->fetchAll();

        header('Content-Type: text/csv');
        header('Content-Disposition: attachment; filename="contacts_' . date('Y-m-d') . '.csv"');
        $out = fopen('php://output', 'w');
        fputcsv($out, ['email', 'first_name', 'last_name', 'company', 'phone', 'status', 'lead_score', 'source', 'created_at']);
        foreach ($contacts as $c) {
            fputcsv($out, $c);
        }
        fclose($out);
        exit;
    }

    private static function applyTags(int $contactId, array $tagNames): void {
        $db = Database::getInstance();
        foreach ($tagNames as $tagName) {
            $tagName = trim($tagName);
            if (empty($tagName)) continue;
            $db->prepare("INSERT OR IGNORE INTO tags (name) VALUES (?)")->execute([$tagName]);
            $stmt = $db->prepare("SELECT id FROM tags WHERE name = ?");
            $stmt->execute([$tagName]);
            $tag = $stmt->fetch();
            if ($tag) {
                $db->prepare("INSERT OR IGNORE INTO contact_tags (contact_id, tag_id) VALUES (?, ?)")->execute([$contactId, $tag['id']]);
            }
        }
    }

    private static function updateListCounts(array $listIds): void {
        $db = Database::getInstance();
        foreach ($listIds as $listId) {
            $db->prepare("UPDATE lists SET contact_count = (SELECT COUNT(*) FROM list_contacts WHERE list_id = ?), updated_at = datetime('now') WHERE id = ?")
                ->execute([$listId, $listId]);
        }
    }
}
