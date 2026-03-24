<?php
class FormController {
    public static function index(): void {
        Router::json(Router::paginate(Database::getInstance(), "SELECT f.*,l.name as list_name FROM forms f LEFT JOIN lists l ON f.list_id=l.id ORDER BY f.created_at DESC", [], (int)($_GET['page'] ?? 1)));
    }
    public static function show(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM forms WHERE id=?"); $stmt->execute([$p['id']]); $f = $stmt->fetch();
        if (!$f) { Router::json(['error'=>'Not found'], 404); return; }
        foreach (['fields','settings','tags_to_apply','style'] as $k) $f[$k] = json_decode($f[$k], true);
        $stmt = $db->prepare("SELECT fs.*,c.email FROM form_submissions fs LEFT JOIN contacts c ON fs.contact_id=c.id WHERE fs.form_id=? ORDER BY fs.created_at DESC LIMIT 20");
        $stmt->execute([$p['id']]); $f['recent_submissions'] = $stmt->fetchAll();
        Router::json($f);
    }
    public static function store(): void {
        $d = Router::body(); if (empty($d['name'])) { Router::json(['error'=>'Name required'], 422); return; }
        $defaults = [['name'=>'email','label'=>'Email','type'=>'email','required'=>true],['name'=>'first_name','label'=>'First Name','type'=>'text','required'=>false]];
        Database::getInstance()->prepare("INSERT INTO forms (name,description,fields,settings,list_id,tags_to_apply,success_message,redirect_url,submit_button_text,style) VALUES (?,?,?,?,?,?,?,?,?,?)")
            ->execute([$d['name'],$d['description']??'',json_encode($d['fields']??$defaults),json_encode($d['settings']??[]),$d['list_id']??null,json_encode($d['tags_to_apply']??[]),$d['success_message']??'Thank you!',$d['redirect_url']??'',$d['submit_button_text']??'Subscribe',json_encode($d['style']??[])]);
        Router::json(['id'=>Database::getInstance()->lastInsertId()], 201);
    }
    public static function update(array $p): void {
        $d = Router::body(); $f = []; $v = [];
        foreach (['name','description','list_id','success_message','redirect_url','submit_button_text','is_active'] as $k) { if (isset($d[$k])) { $f[]="{$k}=?"; $v[]=$d[$k]; } }
        foreach (['fields','settings','tags_to_apply','style'] as $k) { if (isset($d[$k])) { $f[]="{$k}=?"; $v[]=json_encode($d[$k]); } }
        if ($f) { $f[]="updated_at=datetime('now')"; $v[]=$p['id']; Database::getInstance()->prepare("UPDATE forms SET ".implode(',',$f)." WHERE id=?")->execute($v); }
        Router::json(['message'=>'Updated']);
    }
    public static function destroy(array $p): void { Database::getInstance()->prepare("DELETE FROM forms WHERE id=?")->execute([$p['id']]); Router::json(['message'=>'Deleted']); }
    public static function submit(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM forms WHERE id=? AND is_active=1"); $stmt->execute([$p['id']]); $form = $stmt->fetch();
        if (!$form) { Router::json(['error'=>'Form not found'], 404); return; }
        $d = Router::body(); $email = $d['email'] ?? '';
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) { Router::json(['error'=>'Valid email required'], 422); return; }
        $ip = $_SERVER['REMOTE_ADDR'] ?? '';
        $stmt = $db->prepare("SELECT id FROM contacts WHERE email=?"); $stmt->execute([$email]); $ex = $stmt->fetch();
        if ($ex) { $cid = $ex['id']; } else {
            $db->prepare("INSERT INTO contacts (email,first_name,last_name,company,phone,source,ip_address) VALUES (?,?,?,?,?,'form',?)")
                ->execute([$email,$d['first_name']??'',$d['last_name']??'',$d['company']??'',$d['phone']??'',$ip]);
            $cid = $db->lastInsertId();
        }
        if ($form['list_id']) {
            $db->prepare("INSERT OR IGNORE INTO list_contacts (list_id,contact_id) VALUES (?,?)")->execute([$form['list_id'],$cid]);
            $db->prepare("UPDATE lists SET contact_count=(SELECT COUNT(*) FROM list_contacts WHERE list_id=?) WHERE id=?")->execute([$form['list_id'],$form['list_id']]);
        }
        $tags = json_decode($form['tags_to_apply'], true);
        if ($tags) foreach ($tags as $t) {
            $db->prepare("INSERT OR IGNORE INTO tags (name) VALUES (?)")->execute([$t]);
            $tag = $db->prepare("SELECT id FROM tags WHERE name=?"); $tag->execute([$t]); $tr = $tag->fetch();
            if ($tr) $db->prepare("INSERT OR IGNORE INTO contact_tags (contact_id,tag_id) VALUES (?,?)")->execute([$cid,$tr['id']]);
        }
        $db->prepare("INSERT INTO form_submissions (form_id,contact_id,data,ip_address,user_agent) VALUES (?,?,?,?,?)")
            ->execute([$p['id'],$cid,json_encode($d),$ip,$_SERVER['HTTP_USER_AGENT']??'']);
        $db->prepare("UPDATE forms SET total_submissions=total_submissions+1 WHERE id=?")->execute([$p['id']]);
        Router::json(['message'=>$form['success_message'],'redirect_url'=>$form['redirect_url']]);
    }
    public static function embed(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM forms WHERE id=?"); $stmt->execute([$p['id']]); $form = $stmt->fetch();
        if (!$form) { Router::json(['error'=>'Not found'], 404); return; }
        $fields = json_decode($form['fields'], true);
        $siteUrl = Router::getSetting('site_url') ?: '';
        $html = "<div id=\"nf-{$form['id']}\" style=\"max-width:480px;margin:0 auto;padding:24px;background:#1a1a1f;border-radius:12px;font-family:Arial,sans-serif;color:#f2f2f4;\">\n";
        if ($form['name']) $html .= "<h3 style=\"margin:0 0 16px;\">".htmlspecialchars($form['name'])."</h3>\n";
        $html .= "<form onsubmit=\"return nfSubmit(this,{$form['id']})\">\n";
        foreach ($fields as $f) {
            $req = $f['required'] ? ' required' : '';
            $html .= "<div style=\"margin-bottom:12px;\"><label style=\"display:block;margin-bottom:4px;font-size:12px;color:#a8a8b4;\">".htmlspecialchars($f['label']).($f['required']?' *':'')."</label>";
            $html .= "<input type=\"".htmlspecialchars($f['type'])."\" name=\"".htmlspecialchars($f['name'])."\" style=\"width:100%;padding:8px 12px;background:#0f0f12;border:1px solid #2a2a32;border-radius:6px;color:#f2f2f4;font-size:13px;\"{$req}></div>\n";
        }
        $html .= "<button type=\"submit\" style=\"width:100%;padding:12px;background:#FF6B35;color:#fff;border:none;border-radius:6px;font-size:14px;cursor:pointer;font-weight:600;\">".htmlspecialchars($form['submit_button_text'])."</button>\n";
        $html .= "<div id=\"nf-msg-{$form['id']}\" style=\"margin-top:12px;display:none;\"></div></form></div>\n";
        $html .= "<script>function nfSubmit(f,id){var d=new FormData(f),o={};d.forEach(function(v,k){o[k]=v});fetch('{$siteUrl}/api/forms/'+id+'/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)}).then(r=>r.json()).then(r=>{var m=document.getElementById('nf-msg-'+id);m.style.display='block';if(r.redirect_url){window.location=r.redirect_url}else{m.style.color='#22C55E';m.textContent=r.message;f.reset()}}).catch(()=>{var m=document.getElementById('nf-msg-'+id);m.style.display='block';m.style.color='#EF4444';m.textContent='Error'});return false}</script>\n";
        header('Content-Type: text/html'); echo $html; exit;
    }
    public static function submissions(array $p): void {
        $result = Router::paginate(Database::getInstance(),
            "SELECT fs.*,c.email,c.first_name FROM form_submissions fs LEFT JOIN contacts c ON fs.contact_id=c.id WHERE fs.form_id=? ORDER BY fs.created_at DESC",
            [$p['id']], (int)($_GET['page'] ?? 1));
        foreach ($result['items'] as &$s) $s['data'] = json_decode($s['data'], true);
        Router::json($result);
    }
}
