<?php
class FormController {
    public static function index(): void {
        $db = Database::getInstance();
        $result = Router::paginate($db, "SELECT f.*, l.name as list_name FROM forms f LEFT JOIN lists l ON f.list_id = l.id ORDER BY f.created_at DESC", [], (int)($_GET['page'] ?? 1));
        Router::json($result);
    }

    public static function show(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT f.*, l.name as list_name FROM forms f LEFT JOIN lists l ON f.list_id = l.id WHERE f.id = ?");
        $stmt->execute([$params['id']]);
        $form = $stmt->fetch();
        if (!$form) { Router::json(['error' => 'Not found'], 404); return; }

        $form['fields'] = json_decode($form['fields'], true);
        $form['settings'] = json_decode($form['settings'], true);
        $form['tags_to_apply'] = json_decode($form['tags_to_apply'], true);
        $form['style'] = json_decode($form['style'], true);

        // Recent submissions
        $stmt = $db->prepare("SELECT fs.*, c.email, c.first_name, c.last_name FROM form_submissions fs LEFT JOIN contacts c ON fs.contact_id = c.id WHERE fs.form_id = ? ORDER BY fs.created_at DESC LIMIT 20");
        $stmt->execute([$params['id']]);
        $form['recent_submissions'] = $stmt->fetchAll();
        foreach ($form['recent_submissions'] as &$sub) {
            $sub['data'] = json_decode($sub['data'], true);
        }

        Router::json($form);
    }

    public static function store(): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        if (empty($data['name'])) { Router::json(['error' => 'Name is required'], 422); return; }

        $defaultFields = [
            ['name' => 'email', 'label' => 'Email', 'type' => 'email', 'required' => true],
            ['name' => 'first_name', 'label' => 'First Name', 'type' => 'text', 'required' => false],
        ];

        $stmt = $db->prepare("INSERT INTO forms (name, description, fields, settings, list_id, tags_to_apply, success_message, redirect_url, submit_button_text, style) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");
        $stmt->execute([
            $data['name'],
            $data['description'] ?? '',
            json_encode($data['fields'] ?? $defaultFields),
            json_encode($data['settings'] ?? []),
            $data['list_id'] ?? null,
            json_encode($data['tags_to_apply'] ?? []),
            $data['success_message'] ?? 'Thank you for subscribing!',
            $data['redirect_url'] ?? '',
            $data['submit_button_text'] ?? 'Subscribe',
            json_encode($data['style'] ?? []),
        ]);

        $id = $db->lastInsertId();
        ActivityLog::log('form_created', "Form created: {$data['name']}", ['form_id' => $id]);
        Router::json(['id' => $id, 'message' => 'Form created'], 201);
    }

    public static function update(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        $fields = [];
        $values = [];
        foreach (['name', 'description', 'list_id', 'success_message', 'redirect_url', 'submit_button_text', 'is_active'] as $f) {
            if (isset($data[$f])) { $fields[] = "{$f} = ?"; $values[] = $data[$f]; }
        }
        foreach (['fields', 'settings', 'tags_to_apply', 'style'] as $f) {
            if (isset($data[$f])) { $fields[] = "{$f} = ?"; $values[] = json_encode($data[$f]); }
        }

        if ($fields) {
            $fields[] = "updated_at = datetime('now')";
            $values[] = $params['id'];
            $db->prepare("UPDATE forms SET " . implode(', ', $fields) . " WHERE id = ?")->execute($values);
        }

        Router::json(['message' => 'Form updated']);
    }

    public static function destroy(array $params): void {
        $db = Database::getInstance();
        $db->prepare("DELETE FROM forms WHERE id = ?")->execute([$params['id']]);
        Router::json(['message' => 'Form deleted']);
    }

    /**
     * Handle public form submission
     */
    public static function submit(array $params): void {
        $db = Database::getInstance();
        $formId = $params['id'];

        $stmt = $db->prepare("SELECT * FROM forms WHERE id = ? AND is_active = 1");
        $stmt->execute([$formId]);
        $form = $stmt->fetch();
        if (!$form) { Router::json(['error' => 'Form not found'], 404); return; }

        $formFields = json_decode($form['fields'], true);
        $data = Router::getBody();

        // Validate required fields
        foreach ($formFields as $field) {
            if ($field['required'] && empty($data[$field['name']])) {
                Router::json(['error' => "Field '{$field['label']}' is required"], 422);
                return;
            }
        }

        $email = $data['email'] ?? '';
        if (!$email || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
            Router::json(['error' => 'Valid email is required'], 422);
            return;
        }

        $ip = $_SERVER['REMOTE_ADDR'] ?? '';
        $ua = $_SERVER['HTTP_USER_AGENT'] ?? '';

        // Create or update contact
        $stmt = $db->prepare("SELECT id FROM contacts WHERE email = ?");
        $stmt->execute([$email]);
        $existing = $stmt->fetch();

        if ($existing) {
            $contactId = $existing['id'];
            $updates = [];
            $values = [];
            foreach (['first_name', 'last_name', 'company', 'phone'] as $f) {
                if (!empty($data[$f])) { $updates[] = "{$f} = ?"; $values[] = $data[$f]; }
            }
            if ($updates) {
                $values[] = $contactId;
                $db->prepare("UPDATE contacts SET " . implode(', ', $updates) . ", updated_at = datetime('now') WHERE id = ?")->execute($values);
            }
        } else {
            $stmt = $db->prepare("INSERT INTO contacts (email, first_name, last_name, company, phone, source, ip_address, status) VALUES (?, ?, ?, ?, ?, 'form', ?, 'subscribed')");
            $stmt->execute([
                $email,
                $data['first_name'] ?? '',
                $data['last_name'] ?? '',
                $data['company'] ?? '',
                $data['phone'] ?? '',
                $ip,
            ]);
            $contactId = $db->lastInsertId();
        }

        // Add to list
        if ($form['list_id']) {
            $db->prepare("INSERT OR IGNORE INTO list_contacts (list_id, contact_id) VALUES (?, ?)")
                ->execute([$form['list_id'], $contactId]);
            $db->prepare("UPDATE lists SET contact_count = (SELECT COUNT(*) FROM list_contacts WHERE list_id = ?), updated_at = datetime('now') WHERE id = ?")
                ->execute([$form['list_id'], $form['list_id']]);
        }

        // Apply tags
        $tags = json_decode($form['tags_to_apply'], true);
        if ($tags) {
            foreach ($tags as $tagName) {
                $db->prepare("INSERT OR IGNORE INTO tags (name) VALUES (?)")->execute([$tagName]);
                $tag = $db->prepare("SELECT id FROM tags WHERE name = ?");
                $tag->execute([$tagName]);
                $tagRow = $tag->fetch();
                if ($tagRow) {
                    $db->prepare("INSERT OR IGNORE INTO contact_tags (contact_id, tag_id) VALUES (?, ?)")
                        ->execute([$contactId, $tagRow['id']]);
                }
            }
        }

        // Record submission
        $db->prepare("INSERT INTO form_submissions (form_id, contact_id, data, ip_address, user_agent) VALUES (?, ?, ?, ?, ?)")
            ->execute([$formId, $contactId, json_encode($data), $ip, $ua]);

        // Update form stats
        $db->prepare("UPDATE forms SET total_submissions = total_submissions + 1, updated_at = datetime('now') WHERE id = ?")
            ->execute([$formId]);

        // Trigger automations
        AutomationController::triggerForContact('form_submitted', $contactId, ['form_id' => $formId]);
        AutomationController::triggerForContact('contact_subscribed', $contactId);

        $redirectUrl = $form['redirect_url'];
        Router::json([
            'message' => $form['success_message'],
            'redirect_url' => $redirectUrl,
            'contact_id' => $contactId,
        ]);
    }

    /**
     * Generate embeddable HTML for a form
     */
    public static function embed(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM forms WHERE id = ?");
        $stmt->execute([$params['id']]);
        $form = $stmt->fetch();
        if (!$form) { Router::json(['error' => 'Not found'], 404); return; }

        $fields = json_decode($form['fields'], true);
        $style = json_decode($form['style'], true);
        $settings = [];
        $rows = $db->query("SELECT key, value FROM settings WHERE key = 'site_url'")->fetchAll();
        foreach ($rows as $r) $settings[$r['key']] = $r['value'];
        $siteUrl = $settings['site_url'] ?? 'http://localhost:8080';

        $bgColor = $style['background_color'] ?? '#ffffff';
        $textColor = $style['text_color'] ?? '#333333';
        $buttonColor = $style['button_color'] ?? '#6366f1';
        $buttonText = $style['button_text_color'] ?? '#ffffff';
        $borderRadius = $style['border_radius'] ?? '8';
        $fontFamily = $style['font_family'] ?? 'Arial, sans-serif';

        $html = "<!-- MarketFlow Form Embed -->\n";
        $html .= "<div id=\"mf-form-{$form['id']}\" style=\"max-width:480px;margin:0 auto;padding:24px;background:{$bgColor};border-radius:{$borderRadius}px;font-family:{$fontFamily};\">\n";
        if ($form['name']) {
            $html .= "  <h3 style=\"margin:0 0 16px;color:{$textColor};\">" . htmlspecialchars($form['name']) . "</h3>\n";
        }
        if ($form['description']) {
            $html .= "  <p style=\"margin:0 0 16px;color:{$textColor};opacity:0.8;\">" . htmlspecialchars($form['description']) . "</p>\n";
        }
        $html .= "  <form onsubmit=\"return mfSubmit(this,{$form['id']})\" method=\"POST\">\n";
        foreach ($fields as $field) {
            $req = $field['required'] ? ' required' : '';
            $html .= "    <div style=\"margin-bottom:12px;\">\n";
            $html .= "      <label style=\"display:block;margin-bottom:4px;color:{$textColor};font-size:14px;\">" . htmlspecialchars($field['label']) . ($field['required'] ? ' *' : '') . "</label>\n";
            if ($field['type'] === 'textarea') {
                $html .= "      <textarea name=\"" . htmlspecialchars($field['name']) . "\" style=\"width:100%;padding:8px 12px;border:1px solid #ddd;border-radius:4px;font-size:14px;box-sizing:border-box;\"{$req}></textarea>\n";
            } elseif ($field['type'] === 'select' && !empty($field['options'])) {
                $html .= "      <select name=\"" . htmlspecialchars($field['name']) . "\" style=\"width:100%;padding:8px 12px;border:1px solid #ddd;border-radius:4px;font-size:14px;box-sizing:border-box;\"{$req}>\n";
                $html .= "        <option value=\"\">Select...</option>\n";
                foreach ($field['options'] as $opt) {
                    $html .= "        <option value=\"" . htmlspecialchars($opt) . "\">" . htmlspecialchars($opt) . "</option>\n";
                }
                $html .= "      </select>\n";
            } else {
                $html .= "      <input type=\"" . htmlspecialchars($field['type']) . "\" name=\"" . htmlspecialchars($field['name']) . "\" style=\"width:100%;padding:8px 12px;border:1px solid #ddd;border-radius:4px;font-size:14px;box-sizing:border-box;\"{$req}>\n";
            }
            $html .= "    </div>\n";
        }
        $html .= "    <button type=\"submit\" style=\"width:100%;padding:12px;background:{$buttonColor};color:{$buttonText};border:none;border-radius:4px;font-size:16px;cursor:pointer;font-weight:bold;\">" . htmlspecialchars($form['submit_button_text']) . "</button>\n";
        $html .= "    <div id=\"mf-msg-{$form['id']}\" style=\"margin-top:12px;display:none;\"></div>\n";
        $html .= "  </form>\n";
        $html .= "</div>\n";
        $html .= "<script>\n";
        $html .= "function mfSubmit(f,id){var d=new FormData(f),o={};d.forEach(function(v,k){o[k]=v});fetch('" . $siteUrl . "/api/forms/'+id+'/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)}).then(function(r){return r.json()}).then(function(r){var m=document.getElementById('mf-msg-'+id);m.style.display='block';if(r.redirect_url){window.location=r.redirect_url}else{m.style.color='#10b981';m.textContent=r.message||'Thank you!';f.reset()}}).catch(function(){var m=document.getElementById('mf-msg-'+id);m.style.display='block';m.style.color='#ef4444';m.textContent='Something went wrong.'});return false}\n";
        $html .= "</script>\n";

        header('Content-Type: text/html');
        echo $html;
        exit;
    }

    public static function submissions(array $params): void {
        $db = Database::getInstance();
        $page = (int)($_GET['page'] ?? 1);

        $result = Router::paginate($db,
            "SELECT fs.*, c.email, c.first_name, c.last_name FROM form_submissions fs LEFT JOIN contacts c ON fs.contact_id = c.id WHERE fs.form_id = ? ORDER BY fs.created_at DESC",
            [$params['id']], $page
        );

        foreach ($result['items'] as &$sub) {
            $sub['data'] = json_decode($sub['data'], true);
        }

        Router::json($result);
    }
}
