<?php
class PageController {
    public static function index(): void {
        $db = Database::getInstance();
        $result = Router::paginate($db,
            "SELECT lp.*, f.name as form_name FROM landing_pages lp LEFT JOIN forms f ON lp.form_id = f.id ORDER BY lp.created_at DESC",
            [], (int)($_GET['page'] ?? 1)
        );
        Router::json($result);
    }

    public static function show(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT lp.*, f.name as form_name FROM landing_pages lp LEFT JOIN forms f ON lp.form_id = f.id WHERE lp.id = ?");
        $stmt->execute([$params['id']]);
        $page = $stmt->fetch();
        if (!$page) { Router::json(['error' => 'Not found'], 404); return; }
        Router::json($page);
    }

    public static function store(): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        if (empty($data['name'])) { Router::json(['error' => 'Name is required'], 422); return; }

        $slug = $data['slug'] ?? self::generateSlug($data['name']);

        // Check slug uniqueness
        $stmt = $db->prepare("SELECT id FROM landing_pages WHERE slug = ?");
        $stmt->execute([$slug]);
        if ($stmt->fetch()) {
            $slug .= '-' . substr(md5(uniqid()), 0, 6);
        }

        $stmt = $db->prepare("INSERT INTO landing_pages (name, slug, html_content, css_content, form_id, meta_title, meta_description, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)");
        $stmt->execute([
            $data['name'],
            $slug,
            $data['html_content'] ?? self::getDefaultPageContent($data['name']),
            $data['css_content'] ?? '',
            $data['form_id'] ?? null,
            $data['meta_title'] ?? $data['name'],
            $data['meta_description'] ?? '',
            $data['status'] ?? 'draft',
        ]);

        $id = $db->lastInsertId();
        ActivityLog::log('page_created', "Landing page created: {$data['name']}", ['page_id' => $id]);
        Router::json(['id' => $id, 'slug' => $slug, 'message' => 'Landing page created'], 201);
    }

    public static function update(array $params): void {
        $db = Database::getInstance();
        $data = Router::getBody();

        $fields = [];
        $values = [];
        foreach (['name', 'slug', 'html_content', 'css_content', 'form_id', 'meta_title', 'meta_description', 'status'] as $f) {
            if (isset($data[$f])) { $fields[] = "{$f} = ?"; $values[] = $data[$f]; }
        }

        if ($fields) {
            $fields[] = "updated_at = datetime('now')";
            $values[] = $params['id'];
            $db->prepare("UPDATE landing_pages SET " . implode(', ', $fields) . " WHERE id = ?")->execute($values);
        }

        Router::json(['message' => 'Landing page updated']);
    }

    public static function destroy(array $params): void {
        $db = Database::getInstance();
        $db->prepare("DELETE FROM landing_pages WHERE id = ?")->execute([$params['id']]);
        Router::json(['message' => 'Landing page deleted']);
    }

    public static function duplicate(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM landing_pages WHERE id = ?");
        $stmt->execute([$params['id']]);
        $page = $stmt->fetch();
        if (!$page) { Router::json(['error' => 'Not found'], 404); return; }

        $slug = $page['slug'] . '-copy-' . substr(md5(uniqid()), 0, 6);
        $stmt = $db->prepare("INSERT INTO landing_pages (name, slug, html_content, css_content, form_id, meta_title, meta_description, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft')");
        $stmt->execute([$page['name'] . ' (Copy)', $slug, $page['html_content'], $page['css_content'], $page['form_id'], $page['meta_title'], $page['meta_description']]);

        Router::json(['id' => $db->lastInsertId(), 'slug' => $slug, 'message' => 'Page duplicated'], 201);
    }

    /**
     * Render a published landing page by slug
     */
    public static function render(array $params): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM landing_pages WHERE slug = ? AND status = 'published'");
        $stmt->execute([$params['slug']]);
        $page = $stmt->fetch();

        if (!$page) {
            http_response_code(404);
            echo '<!DOCTYPE html><html><head><title>Not Found</title></head><body><h1>Page Not Found</h1></body></html>';
            exit;
        }

        // Increment views
        $db->prepare("UPDATE landing_pages SET total_views = total_views + 1 WHERE id = ?")->execute([$page['id']]);

        // Build form embed if form is linked
        $formEmbed = '';
        if ($page['form_id']) {
            $stmt = $db->prepare("SELECT * FROM forms WHERE id = ? AND is_active = 1");
            $stmt->execute([$page['form_id']]);
            $form = $stmt->fetch();
            if ($form) {
                $fields = json_decode($form['fields'], true);
                $settings = [];
                $rows = $db->query("SELECT key, value FROM settings WHERE key = 'site_url'")->fetchAll();
                foreach ($rows as $r) $settings[$r['key']] = $r['value'];
                $siteUrl = $settings['site_url'] ?? '';

                $formEmbed = '<form id="lp-form" onsubmit="return mfSubmit(this,' . $form['id'] . ')">';
                foreach ($fields as $field) {
                    $req = $field['required'] ? ' required' : '';
                    $formEmbed .= '<div class="form-group">';
                    $formEmbed .= '<label>' . htmlspecialchars($field['label']) . ($field['required'] ? ' *' : '') . '</label>';
                    $formEmbed .= '<input type="' . htmlspecialchars($field['type']) . '" name="' . htmlspecialchars($field['name']) . '" placeholder="' . htmlspecialchars($field['label']) . '"' . $req . '>';
                    $formEmbed .= '</div>';
                }
                $formEmbed .= '<button type="submit">' . htmlspecialchars($form['submit_button_text']) . '</button>';
                $formEmbed .= '<div id="form-message"></div>';
                $formEmbed .= '</form>';
                $formEmbed .= '<script>function mfSubmit(f,id){var d=new FormData(f),o={};d.forEach(function(v,k){o[k]=v});fetch("' . $siteUrl . '/api/forms/"+id+"/submit",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(o)}).then(r=>r.json()).then(r=>{var m=document.getElementById("form-message");m.style.display="block";if(r.redirect_url){window.location=r.redirect_url}else{m.className="success";m.textContent=r.message;f.reset()}}).catch(()=>{var m=document.getElementById("form-message");m.style.display="block";m.className="error";m.textContent="Something went wrong."});return false}</script>';
            }
        }

        $htmlContent = str_replace('{{form}}', $formEmbed, $page['html_content']);

        header('Content-Type: text/html; charset=utf-8');
        echo '<!DOCTYPE html><html><head>';
        echo '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">';
        echo '<title>' . htmlspecialchars($page['meta_title'] ?: $page['name']) . '</title>';
        if ($page['meta_description']) {
            echo '<meta name="description" content="' . htmlspecialchars($page['meta_description']) . '">';
        }
        if ($page['css_content']) {
            echo '<style>' . $page['css_content'] . '</style>';
        }
        echo '<style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:Arial,sans-serif;line-height:1.6}.form-group{margin-bottom:12px}.form-group label{display:block;margin-bottom:4px;font-weight:bold}.form-group input,.form-group textarea,.form-group select{width:100%;padding:10px;border:1px solid #ddd;border-radius:4px;font-size:14px}button[type="submit"]{width:100%;padding:12px;background:#6366f1;color:#fff;border:none;border-radius:4px;font-size:16px;cursor:pointer;font-weight:bold}button[type="submit"]:hover{background:#4f46e5}#form-message{margin-top:12px;padding:10px;border-radius:4px;display:none}.success{background:#d1fae5;color:#065f46}.error{background:#fee2e2;color:#991b1b}</style>';
        echo '</head><body>';
        echo $htmlContent;
        echo '</body></html>';
        exit;
    }

    private static function generateSlug(string $name): string {
        $slug = strtolower(trim($name));
        $slug = preg_replace('/[^a-z0-9-]/', '-', $slug);
        $slug = preg_replace('/-+/', '-', $slug);
        return trim($slug, '-');
    }

    private static function getDefaultPageContent(string $title): string {
        return '<div style="max-width:800px;margin:0 auto;padding:60px 20px;text-align:center;">
<h1 style="font-size:36px;margin-bottom:16px;color:#1e293b;">' . htmlspecialchars($title) . '</h1>
<p style="font-size:18px;color:#64748b;margin-bottom:40px;">Your landing page description goes here.</p>
<div style="max-width:480px;margin:0 auto;">{{form}}</div>
</div>';
    }
}
