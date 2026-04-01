<?php
/**
 * NEXUS Marketing Platform - Configuration
 */
define('APP_NAME', 'NEXUS');
define('APP_VERSION', '3.0.0');
define('APP_ROOT', __DIR__);
define('DATA_DIR', __DIR__ . '/data');
define('DB_PATH', DATA_DIR . '/nexus.sqlite');
define('PUBLIC_DIR', __DIR__ . '/public');

date_default_timezone_set('UTC');
error_reporting(E_ALL);
ini_set('display_errors', 0);
ini_set('log_errors', 1);

// Session
define('SESSION_LIFETIME', 86400 * 7);
