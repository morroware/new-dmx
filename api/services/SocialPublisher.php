<?php
/**
 * Social media publishing service - direct API integration
 * Ported from React services (facebook.js, instagram.js, tiktok.js)
 * Extended with Twitter/X, LinkedIn, Pinterest support
 */
class SocialPublisher {
    private const GRAPH_API = 'https://graph.facebook.com/v25.0';
    private const TIKTOK_API = 'https://open.tiktokapis.com/v2';

    /**
     * Publish to Facebook via Graph API
     */
    public static function facebook(array $cfg, string $content, ?string $mediaUrl = null, ?string $scheduleTime = null): array {
        $logs = [];
        $token = $cfg['meta_access_token'] ?? '';
        $pageId = $cfg['fb_page_id'] ?? '';
        if (!$token || !$pageId) return [['ok' => false, 'msg' => '✗ Facebook: Missing credentials']];

        try {
            $params = ['access_token' => $token];
            if ($mediaUrl) {
                $params['caption'] = $content;
                $params['url'] = $mediaUrl;
                $endpoint = self::GRAPH_API . "/{$pageId}/photos";
            } else {
                $params['message'] = $content;
                $endpoint = self::GRAPH_API . "/{$pageId}/feed";
            }

            if ($scheduleTime) {
                $params['published'] = 'false';
                $params['scheduled_publish_time'] = strtotime($scheduleTime);
            }

            $data = self::httpPost($endpoint, $params, false);

            if (!empty($data['id'])) {
                $action = $scheduleTime ? 'scheduled' : 'published';
                $logs[] = ['ok' => true, 'msg' => "✓ Facebook {$action}: {$data['id']}"];
            } else {
                $err = json_encode($data['error'] ?? $data);
                $logs[] = ['ok' => false, 'msg' => "✗ Facebook: {$err}"];
            }
        } catch (\Exception $e) {
            $logs[] = ['ok' => false, 'msg' => '✗ FB error: ' . $e->getMessage()];
        }
        return $logs;
    }

    /**
     * Publish to Instagram via Graph API (Container → Publish flow)
     */
    public static function instagram(array $cfg, string $content, ?string $mediaUrl = null, string $mediaType = 'IMAGE'): array {
        $logs = [];
        $token = $cfg['meta_access_token'] ?? '';
        $igId = $cfg['ig_user_id'] ?? '';
        if (!$token || !$igId) return [['ok' => false, 'msg' => '✗ Instagram: Missing credentials']];
        if (!$mediaUrl) return [['ok' => false, 'msg' => '✗ Instagram requires a public image/video URL']];

        try {
            // Step 1: Create container
            $containerParams = ['access_token' => $token, 'caption' => $content];
            if ($mediaType === 'REELS') {
                $containerParams['media_type'] = 'REELS';
                $containerParams['video_url'] = $mediaUrl;
            } else {
                $containerParams['image_url'] = $mediaUrl;
            }

            $logs[] = ['ok' => true, 'msg' => '→ Creating IG container...'];
            $container = self::httpPost(self::GRAPH_API . "/{$igId}/media", $containerParams, false);

            if (empty($container['id'])) {
                $err = json_encode($container['error'] ?? $container);
                $logs[] = ['ok' => false, 'msg' => "✗ Container: {$err}"];
                return $logs;
            }
            $logs[] = ['ok' => true, 'msg' => "→ Container: {$container['id']}"];

            // Step 2: Wait for video processing (Reels)
            if ($mediaType === 'REELS') {
                for ($i = 0; $i < 30; $i++) {
                    sleep(3);
                    $status = self::httpGet(self::GRAPH_API . "/{$container['id']}?fields=status_code&access_token={$token}");
                    if (($status['status_code'] ?? '') === 'FINISHED') break;
                    if (($status['status_code'] ?? '') === 'ERROR') {
                        $logs[] = ['ok' => false, 'msg' => '✗ Video processing failed'];
                        return $logs;
                    }
                }
            }

            // Step 3: Publish
            $pubData = self::httpPost(self::GRAPH_API . "/{$igId}/media_publish", [
                'creation_id' => $container['id'],
                'access_token' => $token,
            ], false);

            if (!empty($pubData['id'])) {
                $type = $mediaType === 'REELS' ? 'Reel' : 'post';
                $logs[] = ['ok' => true, 'msg' => "✓ Instagram {$type} published: {$pubData['id']}"];
            } else {
                $err = json_encode($pubData['error'] ?? $pubData);
                $logs[] = ['ok' => false, 'msg' => "✗ Publish: {$err}"];
            }
        } catch (\Exception $e) {
            $logs[] = ['ok' => false, 'msg' => '✗ IG error: ' . $e->getMessage()];
        }
        return $logs;
    }

    /**
     * Publish to TikTok via Content Posting API
     */
    public static function tiktok(array $cfg, string $content, ?string $videoUrl = null): array {
        $logs = [];
        $token = $cfg['tiktok_access_token'] ?? '';
        if (!$token) return [['ok' => false, 'msg' => '✗ TikTok: Missing credentials']];
        if (!$videoUrl) return [['ok' => false, 'msg' => '✗ TikTok requires a video URL']];

        try {
            $headers = ['Authorization: Bearer ' . $token, 'Content-Type: application/json'];

            // Query creator info
            $logs[] = ['ok' => true, 'msg' => '→ Querying TikTok creator info...'];
            self::httpPostJson(self::TIKTOK_API . '/post/publish/creator_info/query/', '{}', $headers);

            // Init upload
            $logs[] = ['ok' => true, 'msg' => '→ Initializing TikTok upload...'];
            $body = json_encode([
                'post_info' => [
                    'title' => mb_substr($content, 0, 150),
                    'privacy_level' => 'PUBLIC_TO_EVERYONE',
                    'disable_comment' => false,
                    'disable_duet' => false,
                    'disable_stitch' => false,
                ],
                'source_info' => [
                    'source' => 'PULL_FROM_URL',
                    'video_url' => $videoUrl,
                ],
            ]);

            $data = self::httpPostJson(self::TIKTOK_API . '/post/publish/video/init/', $body, $headers);

            if (!empty($data['data']['publish_id'])) {
                $logs[] = ['ok' => true, 'msg' => "✓ TikTok upload initiated: {$data['data']['publish_id']}"];
            } else {
                $err = json_encode($data['error'] ?? $data);
                $logs[] = ['ok' => false, 'msg' => "✗ TikTok: {$err}"];
            }
        } catch (\Exception $e) {
            $logs[] = ['ok' => false, 'msg' => '✗ TikTok error: ' . $e->getMessage()];
        }
        return $logs;
    }

    /**
     * Publish to Twitter/X via v2 API
     */
    public static function twitter(array $cfg, string $content, ?string $mediaUrl = null): array {
        $logs = [];
        $token = $cfg['twitter_access_token'] ?? '';
        if (!$token) return [['ok' => false, 'msg' => '✗ Twitter/X: Missing credentials']];

        try {
            $body = json_encode(['text' => mb_substr($content, 0, 280)]);
            $headers = ['Authorization: Bearer ' . $token, 'Content-Type: application/json'];
            $data = self::httpPostJson('https://api.twitter.com/2/tweets', $body, $headers);

            if (!empty($data['data']['id'])) {
                $logs[] = ['ok' => true, 'msg' => "✓ Twitter/X posted: {$data['data']['id']}"];
            } else {
                $err = json_encode($data['errors'] ?? $data);
                $logs[] = ['ok' => false, 'msg' => "✗ Twitter/X: {$err}"];
            }
        } catch (\Exception $e) {
            $logs[] = ['ok' => false, 'msg' => '✗ Twitter/X error: ' . $e->getMessage()];
        }
        return $logs;
    }

    /**
     * Publish to LinkedIn via Share API
     */
    public static function linkedin(array $cfg, string $content, ?string $mediaUrl = null): array {
        $logs = [];
        $token = $cfg['linkedin_access_token'] ?? '';
        if (!$token) return [['ok' => false, 'msg' => '✗ LinkedIn: Missing credentials']];

        try {
            // Get profile URN
            $headers = ['Authorization: Bearer ' . $token];
            $profile = self::httpGet('https://api.linkedin.com/v2/userinfo', $headers);
            $urn = 'urn:li:person:' . ($profile['sub'] ?? '');

            $body = json_encode([
                'author' => $urn,
                'lifecycleState' => 'PUBLISHED',
                'specificContent' => [
                    'com.linkedin.ugc.ShareContent' => [
                        'shareCommentary' => ['text' => $content],
                        'shareMediaCategory' => $mediaUrl ? 'ARTICLE' : 'NONE',
                    ],
                ],
                'visibility' => ['com.linkedin.ugc.MemberNetworkVisibility' => 'PUBLIC'],
            ]);

            $data = self::httpPostJson('https://api.linkedin.com/v2/ugcPosts', $body, array_merge($headers, ['Content-Type: application/json']));

            if (!empty($data['id'])) {
                $logs[] = ['ok' => true, 'msg' => "✓ LinkedIn posted: {$data['id']}"];
            } else {
                $logs[] = ['ok' => false, 'msg' => '✗ LinkedIn: ' . json_encode($data)];
            }
        } catch (\Exception $e) {
            $logs[] = ['ok' => false, 'msg' => '✗ LinkedIn error: ' . $e->getMessage()];
        }
        return $logs;
    }

    // ─── HTTP helpers ───

    private static function httpPost(string $url, array $params, bool $json = true): array {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $json ? json_encode($params) : http_build_query($params),
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 30,
            CURLOPT_HTTPHEADER => $json ? ['Content-Type: application/json'] : [],
        ]);
        $res = curl_exec($ch);
        curl_close($ch);
        return json_decode($res, true) ?? [];
    }

    private static function httpPostJson(string $url, string $body, array $headers): array {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $body,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 30,
            CURLOPT_HTTPHEADER => $headers,
        ]);
        $res = curl_exec($ch);
        curl_close($ch);
        return json_decode($res, true) ?? [];
    }

    private static function httpGet(string $url, array $headers = []): array {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 30,
            CURLOPT_HTTPHEADER => $headers,
        ]);
        $res = curl_exec($ch);
        curl_close($ch);
        return json_decode($res, true) ?? [];
    }
}
