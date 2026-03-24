<?php
/**
 * Simple PHP Router for API and page routing
 */
class Router {
    private array $routes = [];
    private array $middleware = [];

    public function get(string $path, callable $handler): self {
        $this->routes['GET'][$path] = $handler;
        return $this;
    }

    public function post(string $path, callable $handler): self {
        $this->routes['POST'][$path] = $handler;
        return $this;
    }

    public function put(string $path, callable $handler): self {
        $this->routes['PUT'][$path] = $handler;
        return $this;
    }

    public function delete(string $path, callable $handler): self {
        $this->routes['DELETE'][$path] = $handler;
        return $this;
    }

    public function use(callable $middleware): self {
        $this->middleware[] = $middleware;
        return $this;
    }

    public function dispatch(): void {
        $method = $_SERVER['REQUEST_METHOD'];
        $uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

        // Strip trailing slash
        $uri = rtrim($uri, '/') ?: '/';

        // Run middleware
        foreach ($this->middleware as $mw) {
            $result = $mw($method, $uri);
            if ($result === false) return;
        }

        // Try exact match first
        if (isset($this->routes[$method][$uri])) {
            $this->routes[$method][$uri]();
            return;
        }

        // Try pattern matching
        foreach ($this->routes[$method] ?? [] as $pattern => $handler) {
            $regex = $this->patternToRegex($pattern);
            if (preg_match($regex, $uri, $matches)) {
                // Extract named parameters
                $params = array_filter($matches, 'is_string', ARRAY_FILTER_USE_KEY);
                $handler($params);
                return;
            }
        }

        // 404
        http_response_code(404);
        self::json(['error' => 'Not found'], 404);
    }

    private function patternToRegex(string $pattern): string {
        $regex = preg_replace('/\{(\w+)\}/', '(?P<$1>[^/]+)', $pattern);
        return '#^' . $regex . '$#';
    }

    public static function json($data, int $code = 200): void {
        http_response_code($code);
        header('Content-Type: application/json');
        echo json_encode($data, JSON_UNESCAPED_UNICODE);
    }

    public static function getBody(): array {
        $contentType = $_SERVER['CONTENT_TYPE'] ?? '';
        if (str_contains($contentType, 'application/json')) {
            return json_decode(file_get_contents('php://input'), true) ?? [];
        }
        return $_POST;
    }

    public static function paginate(PDO $db, string $query, array $params = [], int $page = 1, int $perPage = PER_PAGE_DEFAULT): array {
        $countQuery = preg_replace('/SELECT .+? FROM/is', 'SELECT COUNT(*) FROM', $query);
        $countQuery = preg_replace('/ORDER BY .+$/i', '', $countQuery);
        $countQuery = preg_replace('/LIMIT .+$/i', '', $countQuery);

        $stmt = $db->prepare($countQuery);
        $stmt->execute($params);
        $total = (int)$stmt->fetchColumn();

        $totalPages = max(1, ceil($total / $perPage));
        $page = max(1, min($page, $totalPages));
        $offset = ($page - 1) * $perPage;

        $query .= " LIMIT {$perPage} OFFSET {$offset}";
        $stmt = $db->prepare($query);
        $stmt->execute($params);
        $items = $stmt->fetchAll();

        return [
            'items' => $items,
            'pagination' => [
                'page' => $page,
                'per_page' => $perPage,
                'total' => $total,
                'total_pages' => $totalPages,
            ]
        ];
    }
}
