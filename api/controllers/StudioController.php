<?php
/**
 * Content Studio - AI generation + social publishing
 */
class StudioController {
    /** Generate text via AI */
    public static function generateText(): void {
        $data = Router::body();
        $model = $data['model'] ?? 'claude';
        $prompt = $data['prompt'] ?? '';
        $contentType = $data['content_type'] ?? 'social_post';
        $tone = $data['tone'] ?? 'professional';
        $platforms = $data['platforms'] ?? ['facebook'];

        if (!$prompt) { Router::json(['error' => 'Prompt is required'], 422); return; }

        $platNames = array_map(fn($p) => ucfirst($p), $platforms);
        $systemPrompt = "You are an expert social media copywriter. Generate engaging " .
            str_replace('_', ' ', $contentType) . " content with a {$tone} tone for: " .
            implode(', ', $platNames) . ". Include relevant hashtags and emojis. Be concise and impactful.";

        $result = AIService::generateText($model, $systemPrompt, $prompt);

        if (isset($result['error'])) {
            Router::json(['error' => $result['error']], 422);
        } else {
            Router::json($result);
        }
    }

    /** Generate images via AI */
    public static function generateImages(): void {
        $data = Router::body();
        $model = $data['model'] ?? 'gemini-free';
        $prompt = $data['prompt'] ?? '';

        if (!$prompt) { Router::json(['error' => 'Prompt is required'], 422); return; }

        $result = AIService::generateImages($model, $prompt);

        if (isset($result['error'])) {
            Router::json(['error' => $result['error']], 422);
        } else {
            Router::json($result);
        }
    }

    /** Publish to social platforms */
    public static function publish(): void {
        $data = Router::body();
        $content = $data['content'] ?? '';
        $platforms = $data['platforms'] ?? [];
        $mediaUrl = $data['media_url'] ?? null;
        $scheduleTime = $data['schedule_time'] ?? null;
        $igMediaType = $data['ig_media_type'] ?? 'IMAGE';

        if (!$content) { Router::json(['error' => 'Content is required'], 422); return; }
        if (empty($platforms)) { Router::json(['error' => 'Select at least one platform'], 422); return; }

        $cfg = Router::getSettings();
        $allLogs = [];

        foreach ($platforms as $platform) {
            $logs = match ($platform) {
                'facebook' => SocialPublisher::facebook($cfg, $content, $mediaUrl, $scheduleTime),
                'instagram' => SocialPublisher::instagram($cfg, $content, $mediaUrl, $igMediaType),
                'tiktok' => SocialPublisher::tiktok($cfg, $content, $mediaUrl),
                'twitter' => SocialPublisher::twitter($cfg, $content, $mediaUrl),
                'linkedin' => SocialPublisher::linkedin($cfg, $content, $mediaUrl),
                default => [['ok' => false, 'msg' => "✗ Unknown platform: {$platform}"]],
            };
            $allLogs = array_merge($allLogs, $logs);
        }

        // Save to social_posts table
        $db = Database::getInstance();
        $status = array_filter($allLogs, fn($l) => $l['ok']) ? 'published' : 'failed';
        $db->prepare("INSERT INTO social_posts (content, platforms, media_urls, status, results, published_at, content_type, tone) VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?)")
            ->execute([
                $content,
                json_encode($platforms),
                json_encode($mediaUrl ? [$mediaUrl] : []),
                $status,
                json_encode($allLogs),
                $data['content_type'] ?? 'social_post',
                $data['tone'] ?? 'professional',
            ]);

        logActivity('social_publish', "Published to " . implode(', ', $platforms));
        Router::json(['logs' => $allLogs, 'post_id' => $db->lastInsertId()]);
    }

    /** Get social post history */
    public static function history(): void {
        $db = Database::getInstance();
        $page = (int)($_GET['page'] ?? 1);
        $result = Router::paginate($db, "SELECT * FROM social_posts ORDER BY created_at DESC", [], $page);
        foreach ($result['items'] as &$item) {
            $item['platforms'] = json_decode($item['platforms'], true);
            $item['media_urls'] = json_decode($item['media_urls'], true);
            $item['results'] = json_decode($item['results'], true);
        }
        Router::json($result);
    }

    /** Get a single post */
    public static function showPost(array $p): void {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM social_posts WHERE id = ?");
        $stmt->execute([$p['id']]);
        $post = $stmt->fetch();
        if (!$post) { Router::json(['error' => 'Not found'], 404); return; }
        $post['platforms'] = json_decode($post['platforms'], true);
        $post['results'] = json_decode($post['results'], true);
        Router::json($post);
    }

    /** Schedule a post */
    public static function schedule(): void {
        $data = Router::body();
        $db = Database::getInstance();

        $db->prepare("INSERT INTO social_posts (content, platforms, media_urls, status, scheduled_at, content_type, tone, ai_model, ai_prompt) VALUES (?, ?, ?, 'scheduled', ?, ?, ?, ?, ?)")
            ->execute([
                $data['content'] ?? '',
                json_encode($data['platforms'] ?? []),
                json_encode($data['media_url'] ? [$data['media_url']] : []),
                $data['schedule_time'] ?? '',
                $data['content_type'] ?? 'social_post',
                $data['tone'] ?? 'professional',
                $data['ai_model'] ?? '',
                $data['ai_prompt'] ?? '',
            ]);

        // Add to calendar
        $postId = $db->lastInsertId();
        $db->prepare("INSERT INTO calendar_events (title, type, ref_id, ref_type, start_date, color) VALUES (?, 'post', ?, 'social_post', ?, '#FF6B35')")
            ->execute([mb_substr($data['content'] ?? 'Scheduled Post', 0, 80), $postId, $data['schedule_time']]);

        Router::json(['id' => $postId, 'message' => 'Post scheduled'], 201);
    }

    /** Delete a post */
    public static function deletePost(array $p): void {
        $db = Database::getInstance();
        $db->prepare("DELETE FROM social_posts WHERE id = ?")->execute([$p['id']]);
        Router::json(['message' => 'Post deleted']);
    }

    /** Get connection status for all platforms */
    public static function connectionStatus(): void {
        $cfg = Router::getSettings();
        Router::json([
            'facebook' => ['connected' => !empty($cfg['meta_access_token']) && !empty($cfg['fb_page_id']), 'name' => 'Facebook'],
            'instagram' => ['connected' => !empty($cfg['meta_access_token']) && !empty($cfg['ig_user_id']), 'name' => 'Instagram'],
            'tiktok' => ['connected' => !empty($cfg['tiktok_access_token']), 'name' => 'TikTok'],
            'twitter' => ['connected' => !empty($cfg['twitter_access_token']), 'name' => 'Twitter/X'],
            'linkedin' => ['connected' => !empty($cfg['linkedin_access_token']), 'name' => 'LinkedIn'],
            'claude' => ['connected' => !empty($cfg['claude_api_key']), 'name' => 'Claude'],
            'openai' => ['connected' => !empty($cfg['openai_api_key']), 'name' => 'OpenAI'],
            'gemini' => ['connected' => !empty($cfg['gemini_api_key']), 'name' => 'Gemini'],
        ]);
    }
}
