<?php
class Router {
    private array $routes = [];

    public function get(string $p, callable $h): void { $this->routes['GET'][$p] = $h; }
    public function post(string $p, callable $h): void { $this->routes['POST'][$p] = $h; }
    public function put(string $p, callable $h): void { $this->routes['PUT'][$p] = $h; }
    public function delete(string $p, callable $h): void { $this->routes['DELETE'][$p] = $h; }

    public function dispatch(): void {
        $method = $_SERVER['REQUEST_METHOD'];
        $uri = rtrim(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH), '/') ?: '/';

        // Exact match
        if (isset($this->routes[$method][$uri])) {
            $this->routes[$method][$uri]();
            return;
        }

        // Pattern match
        foreach ($this->routes[$method] ?? [] as $pattern => $handler) {
            $regex = preg_replace('/\{(\w+)\}/', '(?P<$1>[^/]+)', $pattern);
            if (preg_match('#^' . $regex . '$#', $uri, $matches)) {
                $handler(array_filter($matches, 'is_string', ARRAY_FILTER_USE_KEY));
                return;
            }
        }

        self::json(['error' => 'Not found'], 404);
    }

    public static function json($data, int $code = 200): void {
        http_response_code($code);
        header('Content-Type: application/json');
        echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }

    public static function body(): array {
        $ct = $_SERVER['CONTENT_TYPE'] ?? '';
        if (str_contains($ct, 'application/json')) {
            return json_decode(file_get_contents('php://input'), true) ?? [];
        }
        return $_POST;
    }

    public static function paginate(PDO $db, string $query, array $params = [], int $page = 1, int $perPage = 25): array {
        $countQ = preg_replace('/SELECT .+? FROM/is', 'SELECT COUNT(*) FROM', $query);
        $countQ = preg_replace('/ORDER BY .+$/i', '', $countQ);
        $countQ = preg_replace('/LIMIT .+$/i', '', $countQ);
        $stmt = $db->prepare($countQ);
        $stmt->execute($params);
        $total = (int)$stmt->fetchColumn();
        $totalPages = max(1, ceil($total / $perPage));
        $page = max(1, min($page, $totalPages));
        $offset = ($page - 1) * $perPage;
        $stmt = $db->prepare($query . " LIMIT {$perPage} OFFSET {$offset}");
        $stmt->execute($params);
        return [
            'items' => $stmt->fetchAll(),
            'pagination' => ['page' => $page, 'per_page' => $perPage, 'total' => $total, 'total_pages' => $totalPages],
        ];
    }

    public static function getSetting(string $key): string {
        $db = Database::getInstance();
        $stmt = $db->prepare("SELECT value FROM settings WHERE key = ?");
        $stmt->execute([$key]);
        $row = $stmt->fetch();
        return $row['value'] ?? '';
    }

    public static function getSettings(array $keys = []): array {
        $db = Database::getInstance();
        if ($keys) {
            $ph = implode(',', array_fill(0, count($keys), '?'));
            $stmt = $db->prepare("SELECT key, value FROM settings WHERE key IN ({$ph})");
            $stmt->execute($keys);
        } else {
            $stmt = $db->query("SELECT key, value FROM settings");
        }
        $out = [];
        foreach ($stmt->fetchAll() as $r) $out[$r['key']] = $r['value'];
        return $out;
    }
}

function logActivity(string $type, string $desc, array $meta = []): void {
    $db = Database::getInstance();
    $db->prepare("INSERT INTO activity_log (type, description, metadata) VALUES (?, ?, ?)")
        ->execute([$type, $desc, json_encode($meta)]);
}
