<?php
/**
 * MarketFlow - Marketing Automation Platform
 * Configuration
 */

define('APP_NAME', 'MarketFlow');
define('APP_VERSION', '1.0.0');
define('APP_ROOT', __DIR__);
define('DATA_DIR', __DIR__ . '/data');
define('DB_PATH', DATA_DIR . '/marketflow.sqlite');
define('TEMPLATES_DIR', __DIR__ . '/templates');
define('PUBLIC_DIR', __DIR__ . '/public');
define('UPLOAD_DIR', PUBLIC_DIR . '/assets/uploads');

// Session
define('SESSION_LIFETIME', 86400); // 24 hours

// Default SMTP (configurable from settings)
define('DEFAULT_SMTP_HOST', 'localhost');
define('DEFAULT_SMTP_PORT', 25);
define('DEFAULT_SMTP_ENCRYPTION', ''); // tls, ssl, or empty
define('DEFAULT_SMTP_USERNAME', '');
define('DEFAULT_SMTP_PASSWORD', '');
define('DEFAULT_FROM_EMAIL', 'noreply@example.com');
define('DEFAULT_FROM_NAME', APP_NAME);

// Tracking
define('TRACKING_PIXEL_PATH', '/track/open');
define('TRACKING_CLICK_PATH', '/track/click');

// Pagination
define('PER_PAGE_DEFAULT', 25);

// Timezone
date_default_timezone_set('UTC');

// Error reporting (set to 0 in production)
error_reporting(E_ALL);
ini_set('display_errors', 0);
ini_set('log_errors', 1);
