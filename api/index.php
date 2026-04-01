<?php
/**
 * NEXUS Marketing Platform - API Entry Point
 */
require_once __DIR__ . '/config.php';
require_once __DIR__ . '/Database.php';
require_once __DIR__ . '/Router.php';
require_once __DIR__ . '/Auth.php';
require_once __DIR__ . '/services/AIService.php';
require_once __DIR__ . '/services/SocialPublisher.php';
require_once __DIR__ . '/services/Mailer.php';
require_once __DIR__ . '/controllers/DashboardController.php';
require_once __DIR__ . '/controllers/StudioController.php';
require_once __DIR__ . '/controllers/ContactController.php';
require_once __DIR__ . '/controllers/CampaignController.php';
require_once __DIR__ . '/controllers/TemplateController.php';
require_once __DIR__ . '/controllers/AutomationController.php';
require_once __DIR__ . '/controllers/ListController.php';
require_once __DIR__ . '/controllers/FormController.php';
require_once __DIR__ . '/controllers/PageController.php';
require_once __DIR__ . '/controllers/SettingsController.php';
require_once __DIR__ . '/controllers/TrackingController.php';

Database::migrate();
Auth::init();

header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }

$router = new Router();

// ─── Public routes ───
$router->get('/api/track/open', [TrackingController::class, 'open']);
$router->get('/api/track/click', [TrackingController::class, 'click']);
$router->get('/api/unsubscribe', [TrackingController::class, 'unsubscribe']);
$router->post('/api/unsubscribe', [TrackingController::class, 'unsubscribe']);
$router->post('/api/forms/{id}/submit', [FormController::class, 'submit']);
$router->get('/api/forms/{id}/embed', [FormController::class, 'embed']);
$router->get('/p/{slug}', [PageController::class, 'render']);

// ─── Auth ───
$router->post('/api/auth/login', function () {
    $d = Router::body();
    if (Auth::attempt($d['email'] ?? '', $d['password'] ?? '')) {
        Router::json(['user' => Auth::user()]);
    } else {
        Router::json(['error' => 'Invalid credentials'], 401);
    }
});
$router->post('/api/auth/logout', function () { Auth::logout(); Router::json(['message' => 'OK']); });
$router->get('/api/auth/me', function () {
    Router::json(Auth::check() ? ['user' => Auth::user()] : ['user' => null], Auth::check() ? 200 : 401);
});

// ─── Protected routes (auth check) ───
$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$publicPrefixes = ['/api/track/','/api/unsubscribe','/api/auth/','/api/forms/','/p/'];
$isPublic = false;
foreach ($publicPrefixes as $prefix) { if (str_starts_with($uri, $prefix)) { $isPublic = true; break; } }
if (!$isPublic && str_starts_with($uri, '/api/') && !Auth::check()) {
    Router::json(['error' => 'Unauthorized'], 401); exit;
}

// Dashboard
$router->get('/api/dashboard/stats', [DashboardController::class, 'stats']);
$router->get('/api/dashboard/charts', [DashboardController::class, 'charts']);
$router->get('/api/dashboard/activity', [DashboardController::class, 'activity']);
$router->get('/api/calendar', [DashboardController::class, 'calendar']);
$router->post('/api/calendar', [DashboardController::class, 'calendarStore']);
$router->put('/api/calendar/{id}', [DashboardController::class, 'calendarUpdate']);
$router->delete('/api/calendar/{id}', [DashboardController::class, 'calendarDelete']);

// Studio (AI + Social)
$router->post('/api/studio/generate-text', [StudioController::class, 'generateText']);
$router->post('/api/studio/generate-images', [StudioController::class, 'generateImages']);
$router->post('/api/studio/publish', [StudioController::class, 'publish']);
$router->post('/api/studio/schedule', [StudioController::class, 'schedule']);
$router->get('/api/studio/history', [StudioController::class, 'history']);
$router->get('/api/studio/posts/{id}', [StudioController::class, 'showPost']);
$router->delete('/api/studio/posts/{id}', [StudioController::class, 'deletePost']);
$router->get('/api/studio/connections', [StudioController::class, 'connectionStatus']);

// Contacts
$router->get('/api/contacts', [ContactController::class, 'index']);
$router->get('/api/contacts/export', [ContactController::class, 'export']);
$router->post('/api/contacts', [ContactController::class, 'store']);
$router->post('/api/contacts/import', [ContactController::class, 'import']);
$router->post('/api/contacts/bulk', [ContactController::class, 'bulk']);
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
$router->post('/api/campaigns/{id}/duplicate', [CampaignController::class, 'duplicate']);
$router->get('/api/campaigns/{id}/preview', [CampaignController::class, 'preview']);
$router->post('/api/campaigns/{id}/test', [CampaignController::class, 'sendTest']);

// Templates
$router->get('/api/templates', [TemplateController::class, 'index']);
$router->get('/api/templates/starters', [TemplateController::class, 'starters']);
$router->post('/api/templates', [TemplateController::class, 'store']);
$router->get('/api/templates/{id}', [TemplateController::class, 'show']);
$router->put('/api/templates/{id}', [TemplateController::class, 'update']);
$router->delete('/api/templates/{id}', [TemplateController::class, 'destroy']);
$router->post('/api/templates/{id}/duplicate', [TemplateController::class, 'duplicate']);

// Automations
$router->get('/api/automations', [AutomationController::class, 'index']);
$router->get('/api/automations/trigger-types', [AutomationController::class, 'triggerTypes']);
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
$router->post('/api/settings/test-email', [SettingsController::class, 'testEmail']);
$router->get('/api/tags', [SettingsController::class, 'tags']);
$router->post('/api/tags', [SettingsController::class, 'createTag']);
$router->put('/api/tags/{id}', [SettingsController::class, 'updateTag']);
$router->delete('/api/tags/{id}', [SettingsController::class, 'deleteTag']);
$router->get('/api/users', [SettingsController::class, 'users']);
$router->post('/api/users', [SettingsController::class, 'createUser']);
$router->put('/api/profile', [SettingsController::class, 'updateProfile']);

$router->dispatch();
