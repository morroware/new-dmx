<?php
class ActivityLog {
    public static function log(string $type, string $description, array $metadata = []): void {
        $db = Database::getInstance();
        $userId = Auth::userId();
        $ip = $_SERVER['REMOTE_ADDR'] ?? '';

        $stmt = $db->prepare("INSERT INTO activity_log (user_id, type, description, metadata, ip_address) VALUES (?, ?, ?, ?, ?)");
        $stmt->execute([$userId, $type, $description, json_encode($metadata), $ip]);
    }
}
