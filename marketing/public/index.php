<?php
/**
 * MarketFlow - Marketing Automation Platform
 * Main Entry Point
 */

require_once __DIR__ . '/../config.php';
require_once APP_ROOT . '/src/Database.php';
require_once APP_ROOT . '/src/Router.php';
require_once APP_ROOT . '/src/Auth.php';
require_once APP_ROOT . '/src/Mailer.php';
require_once APP_ROOT . '/src/services/ActivityLog.php';
require_once APP_ROOT . '/src/controllers/DashboardController.php';
require_once APP_ROOT . '/src/controllers/ContactController.php';
require_once APP_ROOT . '/src/controllers/CampaignController.php';
require_once APP_ROOT . '/src/controllers/TemplateController.php';
require_once APP_ROOT . '/src/controllers/AutomationController.php';
require_once APP_ROOT . '/src/controllers/ListController.php';
require_once APP_ROOT . '/src/controllers/FormController.php';
require_once APP_ROOT . '/src/controllers/PageController.php';
require_once APP_ROOT . '/src/controllers/SettingsController.php';
require_once APP_ROOT . '/src/controllers/TrackingController.php';

// Initialize
Database::migrate();
Auth::init();

$router = new Router();

// CORS headers for API
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

// ─── Public routes (no auth required) ───

// Tracking
$router->get('/track/open', [TrackingController::class, 'trackOpen']);
$router->get('/track/click', [TrackingController::class, 'trackClick']);

// Unsubscribe
$router->get('/unsubscribe', [TrackingController::class, 'unsubscribe']);
$router->post('/unsubscribe', [TrackingController::class, 'unsubscribe']);

// Public form submission
$router->post('/api/forms/{id}/submit', [FormController::class, 'submit']);

// Form embed
$router->get('/api/forms/{id}/embed', [FormController::class, 'embed']);

// Landing pages
$router->get('/p/{slug}', [PageController::class, 'render']);

// Auth routes
$router->post('/api/auth/login', function () {
    $data = Router::getBody();
    $email = $data['email'] ?? '';
    $password = $data['password'] ?? '';

    if (empty($email) || empty($password)) {
        Router::json(['error' => 'Email and password are required'], 422);
        return;
    }

    if (Auth::attempt($email, $password)) {
        Router::json(['user' => Auth::user(), 'message' => 'Login successful']);
    } else {
        Router::json(['error' => 'Invalid credentials'], 401);
    }
});

$router->post('/api/auth/logout', function () {
    Auth::logout();
    Router::json(['message' => 'Logged out']);
});

$router->get('/api/auth/me', function () {
    if (Auth::check()) {
        Router::json(['user' => Auth::user()]);
    } else {
        Router::json(['user' => null], 401);
    }
});

// Cron endpoint for automation processing
$router->get('/api/cron/automations', function () {
    // Simple auth via query param for cron jobs
    $key = $_GET['key'] ?? '';
    $db = Database::getInstance();
    $stmt = $db->prepare("SELECT value FROM settings WHERE key = 'cron_key'");
    $stmt->execute();
    $row = $stmt->fetch();
    // Allow if no key is configured or if it matches
    if ($row && $row['value'] && $row['value'] !== $key) {
        Router::json(['error' => 'Unauthorized'], 401);
        return;
    }
    AutomationController::processQueue();
});

// Cron for scheduled campaigns
$router->get('/api/cron/campaigns', function () {
    $db = Database::getInstance();
    $now = date('Y-m-d H:i:s');
    $stmt = $db->prepare("SELECT id FROM campaigns WHERE status = 'scheduled' AND scheduled_at <= ?");
    $stmt->execute([$now]);
    $campaigns = $stmt->fetchAll();
    $sent = 0;
    foreach ($campaigns as $campaign) {
        CampaignController::send(['id' => $campaign['id']]);
        $sent++;
    }
    Router::json(['processed' => $sent]);
});

// ─── Protected API routes ───

// Auth middleware for /api/* routes (excluding public ones above)
$router->use(function (string $method, string $uri) {
    // Skip auth for public routes
    $publicPrefixes = ['/track/', '/unsubscribe', '/api/auth/', '/api/forms/', '/api/cron/', '/p/'];
    foreach ($publicPrefixes as $prefix) {
        if (str_starts_with($uri, $prefix)) return true;
    }

    // Require auth for all /api/* routes
    if (str_starts_with($uri, '/api/')) {
        if (!Auth::check()) {
            Router::json(['error' => 'Unauthorized'], 401);
            return false;
        }
    }
    return true;
});

// Dashboard
$router->get('/api/dashboard/stats', [DashboardController::class, 'stats']);
$router->get('/api/dashboard/charts', [DashboardController::class, 'charts']);
$router->get('/api/dashboard/activity', [DashboardController::class, 'recentActivity']);

// Contacts
$router->get('/api/contacts', [ContactController::class, 'index']);
$router->get('/api/contacts/export', [ContactController::class, 'export']);
$router->post('/api/contacts', [ContactController::class, 'store']);
$router->post('/api/contacts/import', [ContactController::class, 'import']);
$router->post('/api/contacts/bulk', [ContactController::class, 'bulkAction']);
$router->get('/api/contacts/{id}', [ContactController::class, 'show']);
$router->put('/api/contacts/{id}', [ContactController::class, 'update']);
$router->delete('/api/contacts/{id}', [ContactController::class, 'destroy']);

// Lists
$router->get('/api/lists', [ListController::class, 'index']);
$router->post('/api/lists', [ListController::class, 'store']);
$router->get('/api/lists/{id}', [ListController::class, 'show']);
$router->put('/api/lists/{id}', [ListController::class, 'update']);
$router->delete('/api/lists/{id}', [ListController::class, 'destroy']);
$router->post('/api/lists/{id}/contacts', [ListController::class, 'addContacts']);
$router->delete('/api/lists/{id}/contacts', [ListController::class, 'removeContacts']);

// Campaigns
$router->get('/api/campaigns', [CampaignController::class, 'index']);
$router->post('/api/campaigns', [CampaignController::class, 'store']);
$router->get('/api/campaigns/{id}', [CampaignController::class, 'show']);
$router->put('/api/campaigns/{id}', [CampaignController::class, 'update']);
$router->delete('/api/campaigns/{id}', [CampaignController::class, 'destroy']);
$router->post('/api/campaigns/{id}/send', [CampaignController::class, 'send']);
$router->post('/api/campaigns/{id}/schedule', [CampaignController::class, 'schedule']);
$router->post('/api/campaigns/{id}/duplicate', [CampaignController::class, 'duplicate']);
$router->get('/api/campaigns/{id}/preview', [CampaignController::class, 'preview']);
$router->post('/api/campaigns/{id}/test', [CampaignController::class, 'sendTest']);

// Templates
$router->get('/api/templates', [TemplateController::class, 'index']);
$router->get('/api/templates/starters', [TemplateController::class, 'getStarters']);
$router->post('/api/templates', [TemplateController::class, 'store']);
$router->get('/api/templates/{id}', [TemplateController::class, 'show']);
$router->put('/api/templates/{id}', [TemplateController::class, 'update']);
$router->delete('/api/templates/{id}', [TemplateController::class, 'destroy']);
$router->post('/api/templates/{id}/duplicate', [TemplateController::class, 'duplicate']);

// Automations
$router->get('/api/automations', [AutomationController::class, 'index']);
$router->get('/api/automations/trigger-types', [AutomationController::class, 'getTriggerTypes']);
$router->post('/api/automations', [AutomationController::class, 'store']);
$router->get('/api/automations/{id}', [AutomationController::class, 'show']);
$router->put('/api/automations/{id}', [AutomationController::class, 'update']);
$router->delete('/api/automations/{id}', [AutomationController::class, 'destroy']);
$router->post('/api/automations/{id}/activate', [AutomationController::class, 'activate']);
$router->post('/api/automations/{id}/pause', [AutomationController::class, 'pause']);

// Forms
$router->get('/api/forms', [FormController::class, 'index']);
$router->post('/api/forms', [FormController::class, 'store']);
$router->get('/api/forms/{id}', [FormController::class, 'show']);
$router->put('/api/forms/{id}', [FormController::class, 'update']);
$router->delete('/api/forms/{id}', [FormController::class, 'destroy']);
$router->get('/api/forms/{id}/submissions', [FormController::class, 'submissions']);

// Landing Pages
$router->get('/api/pages', [PageController::class, 'index']);
$router->post('/api/pages', [PageController::class, 'store']);
$router->get('/api/pages/{id}', [PageController::class, 'show']);
$router->put('/api/pages/{id}', [PageController::class, 'update']);
$router->delete('/api/pages/{id}', [PageController::class, 'destroy']);
$router->post('/api/pages/{id}/duplicate', [PageController::class, 'duplicate']);

// Settings
$router->get('/api/settings', [SettingsController::class, 'index']);
$router->post('/api/settings', [SettingsController::class, 'update']);
$router->post('/api/settings/test-smtp', [SettingsController::class, 'testSmtp']);
$router->post('/api/settings/test-email', [SettingsController::class, 'sendTestEmail']);

// Tags
$router->get('/api/tags', [SettingsController::class, 'listTags']);
$router->post('/api/tags', [SettingsController::class, 'createTag']);
$router->put('/api/tags/{id}', [SettingsController::class, 'updateTag']);
$router->delete('/api/tags/{id}', [SettingsController::class, 'deleteTag']);

// Custom fields
$router->get('/api/custom-fields', [SettingsController::class, 'listCustomFields']);
$router->post('/api/custom-fields', [SettingsController::class, 'createCustomField']);
$router->delete('/api/custom-fields/{id}', [SettingsController::class, 'deleteCustomField']);

// Users
$router->get('/api/users', [SettingsController::class, 'listUsers']);
$router->post('/api/users', [SettingsController::class, 'createUser']);
$router->put('/api/profile', [SettingsController::class, 'updateProfile']);

// Serve the SPA for all non-API routes
$router->get('/', function () {
    readfile(PUBLIC_DIR . '/app.html');
});

// Catch-all for SPA routing
$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
if (!str_starts_with($uri, '/api/') && !str_starts_with($uri, '/track/') && !str_starts_with($uri, '/p/') && $uri !== '/unsubscribe' && !preg_match('/\.(css|js|png|jpg|gif|ico|svg|woff|woff2|ttf)$/', $uri)) {
    if (!isset($router)) {
        require_once __DIR__ . '/../config.php';
    }
}

$router->dispatch();
