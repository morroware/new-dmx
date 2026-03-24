<?php
/**
 * AI content generation service - server-side proxy
 * Ported from React ai.js - keys are now stored server-side for security
 */
class AIService {
    /**
     * Generate text using selected AI model
     */
    public static function generateText(string $model, string $systemPrompt, string $userPrompt): array {
        $cfg = Router::getSettings(['claude_api_key', 'openai_api_key', 'gemini_api_key']);

        try {
            if ($model === 'claude') {
                $key = $cfg['claude_api_key'] ?? '';
                if (!$key) return ['error' => 'Claude API key not configured'];

                $res = self::post('https://api.anthropic.com/v1/messages', [
                    'model' => 'claude-sonnet-4-20250514',
                    'max_tokens' => 1024,
                    'system' => $systemPrompt,
                    'messages' => [['role' => 'user', 'content' => $userPrompt]],
                ], [
                    'Content-Type: application/json',
                    'x-api-key: ' . $key,
                    'anthropic-version: 2023-06-01',
                ]);

                return ['text' => $res['content'][0]['text'] ?? '', 'model' => 'Claude Sonnet 4'];
            }

            if ($model === 'openai') {
                $key = $cfg['openai_api_key'] ?? '';
                if (!$key) return ['error' => 'OpenAI API key not configured'];

                $res = self::post('https://api.openai.com/v1/chat/completions', [
                    'model' => 'gpt-4.1-mini',
                    'max_tokens' => 1024,
                    'messages' => [
                        ['role' => 'system', 'content' => $systemPrompt],
                        ['role' => 'user', 'content' => $userPrompt],
                    ],
                ], [
                    'Content-Type: application/json',
                    'Authorization: Bearer ' . $key,
                ]);

                return ['text' => $res['choices'][0]['message']['content'] ?? '', 'model' => 'GPT-4.1 Mini'];
            }

            // Gemini (default)
            $key = $cfg['gemini_api_key'] ?? '';
            if (!$key) return ['error' => 'Gemini API key not configured'];

            $res = self::post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={$key}",
                ['contents' => [['parts' => [['text' => "{$systemPrompt}\n\n{$userPrompt}"]]]]],
                ['Content-Type: application/json']
            );

            return ['text' => $res['candidates'][0]['content']['parts'][0]['text'] ?? '', 'model' => 'Gemini 2.5 Flash'];
        } catch (\Exception $e) {
            return ['error' => $e->getMessage()];
        }
    }

    /**
     * Generate images using selected AI model
     */
    public static function generateImages(string $model, string $prompt): array {
        $cfg = Router::getSettings(['openai_api_key', 'gemini_api_key']);

        try {
            if (str_starts_with($model, 'openai')) {
                $key = $cfg['openai_api_key'] ?? '';
                if (!$key) return ['error' => 'OpenAI API key not configured'];

                $modelId = $model === 'openai-flag' ? 'gpt-image-1' : 'gpt-image-1-mini';
                $res = self::post('https://api.openai.com/v1/images/generations', [
                    'model' => $modelId,
                    'prompt' => $prompt,
                    'n' => 1,
                    'size' => '1024x1024',
                    'quality' => 'medium',
                ], [
                    'Content-Type: application/json',
                    'Authorization: Bearer ' . $key,
                ]);

                if (!empty($res['data'])) {
                    $images = [];
                    foreach ($res['data'] as $img) {
                        $images[] = !empty($img['b64_json']) ? "data:image/png;base64,{$img['b64_json']}" : ($img['url'] ?? '');
                    }
                    return ['images' => $images];
                }
                return ['error' => json_encode($res['error'] ?? $res)];
            }

            if ($model === 'imagen4') {
                $key = $cfg['gemini_api_key'] ?? '';
                if (!$key) return ['error' => 'Gemini API key not configured'];

                $res = self::post(
                    "https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={$key}",
                    ['instances' => [['prompt' => $prompt]], 'parameters' => ['sampleCount' => 1]],
                    ['Content-Type: application/json']
                );

                if (!empty($res['predictions'])) {
                    return ['images' => array_map(fn($p) => "data:image/png;base64,{$p['bytesBase64Encoded']}", $res['predictions'])];
                }
                return ['error' => json_encode($res)];
            }

            // Gemini free (default)
            $key = $cfg['gemini_api_key'] ?? '';
            if (!$key) return ['error' => 'Gemini API key not configured'];

            $res = self::post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={$key}",
                [
                    'contents' => [['parts' => [['text' => $prompt]]]],
                    'generationConfig' => ['responseModalities' => ['TEXT', 'IMAGE']],
                ],
                ['Content-Type: application/json']
            );

            $parts = $res['candidates'][0]['content']['parts'] ?? [];
            $images = [];
            foreach ($parts as $p) {
                if (!empty($p['inlineData'])) {
                    $images[] = "data:{$p['inlineData']['mimeType']};base64,{$p['inlineData']['data']}";
                }
            }
            return $images ? ['images' => $images] : ['error' => 'No image returned'];
        } catch (\Exception $e) {
            return ['error' => $e->getMessage()];
        }
    }

    private static function post(string $url, array $data, array $headers): array {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => json_encode($data),
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 60,
            CURLOPT_HTTPHEADER => $headers,
        ]);
        $res = curl_exec($ch);
        $err = curl_error($ch);
        curl_close($ch);
        if ($err) throw new \Exception("cURL error: {$err}");
        return json_decode($res, true) ?? [];
    }
}
