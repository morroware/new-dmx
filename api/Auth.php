<?php
class Auth {
    public static function init(): void {
        if (session_status() === PHP_SESSION_NONE) {
            session_set_cookie_params(['lifetime' => SESSION_LIFETIME, 'httponly' => true, 'samesite' => 'Lax']);
            session_start();
        }
    }

    public static function attempt(string $email, string $password): bool {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT * FROM users WHERE email = ? AND is_active = 1");
        $stmt->execute([$email]);
        $user = $stmt->fetch();
        if (!$user) return false;

        if (empty($user['password_hash'])) {
            $db->prepare("UPDATE users SET password_hash = ? WHERE id = ?")
                ->execute([password_hash($password, PASSWORD_BCRYPT), $user['id']]);
        } elseif (!password_verify($password, $user['password_hash'])) {
            return false;
        }

        $_SESSION['user_id'] = $user['id'];
        $_SESSION['user_email'] = $user['email'];
        $_SESSION['user_name'] = $user['name'];
        $_SESSION['user_role'] = $user['role'];
        $db->prepare("UPDATE users SET last_login = datetime('now') WHERE id = ?")->execute([$user['id']]);
        return true;
    }

    public static function check(): bool { return isset($_SESSION['user_id']); }
    public static function user(): ?array {
        return self::check() ? ['id' => $_SESSION['user_id'], 'email' => $_SESSION['user_email'], 'name' => $_SESSION['user_name'], 'role' => $_SESSION['user_role']] : null;
    }
    public static function logout(): void { session_destroy(); $_SESSION = []; }
    public static function requireAuth(): void {
        if (!self::check()) { Router::json(['error' => 'Unauthorized'], 401); exit; }
    }
}
