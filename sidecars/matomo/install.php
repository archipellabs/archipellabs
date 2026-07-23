<?php

declare(strict_types=1);

/**
 * Headless Matomo bootstrap — the tracking-stack counterpart to the PrestaShop
 * provisioning sidecar. Runs once from the matomo image against matomodb and, via
 * Matomo's own classes, does what the web install wizard would: write
 * config.ini.php, create the schema, install the plugins, create the super user,
 * and create the TimberWorks site as an Ecommerce site (→ idSite 1). Idempotent.
 *
 * Note: a CLI bootstrap loads NO plugins by default (the console does it via the
 * FrontController). We must call Manager::loadActivatedPlugins() right after
 * Environment init — otherwise plugin tables are missing from createTables() and
 * measurable types like 'website' aren't registered, so addSite() fails.
 *
 * Config comes from the environment (see config/matomo/default.env). Values are
 * version-coupled to Matomo's internal API on purpose — pinned to matomo:5-apache.
 */

use Piwik\Access;
use Piwik\Common;
use Piwik\Config;
use Piwik\Db;
use Piwik\DbHelper;
use Piwik\Application\Environment;
use Piwik\Plugin\Manager as PluginManager;
use Piwik\Plugins\SitesManager\API as SitesManagerApi;
use Piwik\Plugins\UserCountry\LocationProvider;
use Piwik\Plugins\UsersManager\API as UsersManagerApi;

const ROOT = '/var/www/html';
const PREFIX = 'matomo_';

function say(string $msg): void
{
    fwrite(STDOUT, '[matomo-sidecar] ' . $msg . PHP_EOL);
}

function env(string $key, string $default = ''): string
{
    $value = getenv($key);

    return $value === false || $value === '' ? $default : $value;
}

/**
 * Download a gzipped MaxMind-format DB and install it atomically at $dest — but
 * only after the same reader Matomo uses confirms it is a valid, queryable
 * database. Returns false (leaving nothing behind) on any failure, so a
 * truncated or corrupt download never becomes a sticky, silently-broken DB that
 * the `is_file` guard would then refuse to re-fetch.
 */
function download_geoip_db(string $url, string $dest): bool
{
    $tmpGz = $dest . '.gz.part';
    $tmpDb = $dest . '.part';
    $ok = false;
    try {
        $src = @fopen($url, 'rb');
        if ($src === false) {
            return false; // e.g. this month's file is not published yet (404)
        }
        $dst = @fopen($tmpGz, 'wb');
        if ($dst === false) {
            fclose($src);
            return false; // misc/ not writable
        }
        $copied = stream_copy_to_stream($src, $dst);
        fclose($src);
        fclose($dst);
        if ($copied === false || $copied < 1_000_000) {
            return false; // truncated or empty response, not a ~100 MB database
        }

        $in = gzopen($tmpGz, 'rb');
        $out = fopen($tmpDb, 'wb');
        while (!gzeof($in)) {
            $chunk = gzread($in, 1 << 20);
            if ($chunk === false) {
                break; // corrupt gzip stream — the reader check below will reject it
            }
            fwrite($out, $chunk);
        }
        gzclose($in);
        fclose($out);

        // Decisive check: open it exactly as Matomo will. The Reader constructor
        // parses and validates the DB metadata (throws on a truncated/garbage
        // file); the lookup exercises the data section.
        $reader = new \MaxMind\Db\Reader($tmpDb);
        $reader->get('8.8.8.8');
        $reader->close();

        $ok = rename($tmpDb, $dest);
        return $ok;
    } catch (\Throwable $e) {
        say('discarding invalid GeoIP download: ' . $e->getMessage());
        return false;
    } finally {
        if (is_file($tmpGz)) {
            unlink($tmpGz);
        }
        if (!$ok && is_file($tmpDb)) {
            unlink($tmpDb);
        }
    }
}

$dbHost = env('MATOMO_DATABASE_HOST', 'matomodb');
$dbName = env('MATOMO_DATABASE_DBNAME', env('MYSQL_DATABASE', 'matomo'));
$dbUser = env('MATOMO_DATABASE_USERNAME', env('MYSQL_USER', 'matomo'));
$dbPass = env('MATOMO_DATABASE_PASSWORD', env('MYSQL_PASSWORD', 'matomo'));

$adminLogin = env('MATOMO_ADMIN_LOGIN', 'admin');
$adminPass = env('MATOMO_ADMIN_PASSWORD', 'changeme_demo');
$adminEmail = env('MATOMO_ADMIN_EMAIL', 'admin@timberworks.test');
$siteName = env('MATOMO_SITE_NAME', 'TimberWorks');
$siteUrl = env('MATOMO_SITE_URL', 'https://localhost/');

// 1. Wait for the database to accept connections (no healthcheck on matomodb).
// Since PHP 8.1 mysqli THROWS on a refused connection instead of returning false,
// so a not-yet-ready DB would be an uncaught fatal (exit 255, and no output with
// display_errors off) rather than a retry. Turn reporting off so the loop can poll.
mysqli_report(MYSQLI_REPORT_OFF);
$deadline = time() + 120;
while (true) {
    $link = @mysqli_connect($dbHost, $dbUser, $dbPass, $dbName);
    if ($link instanceof mysqli) {
        mysqli_close($link);
        break;
    }
    if (time() > $deadline) {
        fwrite(STDERR, "[matomo-sidecar] database {$dbHost} not reachable after 120s\n");
        exit(1);
    }
    say("waiting for database {$dbHost}...");
    sleep(3);
}

// 2. Seed config.ini.php so Matomo boots against our database.
$configFile = ROOT . '/config/config.ini.php';
if (!is_file($configFile)) {
    $salt = bin2hex(random_bytes(16));
    $ini = "; <?php exit; ?> DO NOT REMOVE THIS LINE\n"
        . "; generated by the matomo provisioning sidecar\n\n"
        . "[database]\n"
        . "host = \"{$dbHost}\"\n"
        . "username = \"{$dbUser}\"\n"
        . "password = \"{$dbPass}\"\n"
        . "dbname = \"{$dbName}\"\n"
        . "tables_prefix = \"" . PREFIX . "\"\n"
        . "charset = \"utf8mb4\"\n\n"
        . "[General]\n"
        . "salt = \"{$salt}\"\n"
        . "trusted_hosts[] = \"localhost\"\n"
        . "trusted_hosts[] = \"localhost:8080\"\n"
        . "trusted_hosts[] = \"gateway\"\n"
        . "trusted_hosts[] = \"matomo\"\n";
    if (!is_dir(dirname($configFile))) {
        mkdir(dirname($configFile), 0o755, true);
    }
    file_put_contents($configFile, $ini);
    say('wrote config.ini.php');
} else {
    say('config.ini.php already present');
}

// 3. Boot the Matomo kernel (mirrors the console bootstrap) and LOAD the plugins.
define('PIWIK_DOCUMENT_ROOT', ROOT);
define('PIWIK_INCLUDE_PATH', ROOT);
require ROOT . '/core/bootstrap.php';

$environment = new Environment('cli');
$environment->init();
PluginManager::getInstance()->loadActivatedPlugins(); // must precede createTables/addSite

// 4. Create the schema on a fresh database (now includes plugin tables).
$installed = false;
try {
    $installed = DbHelper::getInstallVersion() !== '';
} catch (\Throwable $e) {
    $installed = false; // the option table doesn't exist yet
}

if (!$installed) {
    say('creating Matomo tables...');
    DbHelper::createTables();
    DbHelper::createAnonymousUser();
    DbHelper::recordInstallVersion();
    say('schema created');
} else {
    say('schema already present (install version ' . DbHelper::getInstallVersion() . ')');
}

// 5. Install plugins, create the super user + the Ecommerce site (as superuser).
try {
    Access::doAsSuperUser(function () use (
        $adminLogin, $adminPass, $adminEmail, $siteName, $siteUrl
    ) {
        PluginManager::getInstance()->installLoadedPlugins(); // idempotent

        $users = UsersManagerApi::getInstance();
        $userExists = (bool) Db::fetchOne(
            'SELECT COUNT(*) FROM ' . Common::prefixTable('user') . ' WHERE login = ?',
            [$adminLogin]
        );
        if (!$userExists) {
            $users->addUser($adminLogin, $adminPass, $adminEmail);
            $users->setSuperUserAccess($adminLogin, true);
            say("created super user '{$adminLogin}'");
        } else {
            say("super user '{$adminLogin}' already exists");
        }

        $siteCount = (int) Db::fetchOne('SELECT COUNT(*) FROM ' . Common::prefixTable('site'));
        if ($siteCount === 0) {
            $idSite = SitesManagerApi::getInstance()->addSite($siteName, [$siteUrl], 1); // 3rd arg = ecommerce
            say("created Ecommerce site '{$siteName}' -> idSite {$idSite}");
        } else {
            say("site(s) already present ({$siteCount}) — leaving as is");
        }
    });
} catch (\Throwable $e) {
    fwrite(STDERR, '[matomo-sidecar] ERROR during setup: ' . $e->getMessage() . "\n");
    fwrite(STDERR, $e->getTraceAsString() . "\n");
    exit(1);
}

// 6. Trust the gateway's X-Forwarded-For so the simulator's spoofed client IPs
// land in the visit log (the gateway appends its own peer IP after the client
// value; Matomo reads the first entry). Config-API merge, not a file rewrite —
// config.ini.php usually predates this step.
$config = Config::getInstance();
$general = $config->General;
$proxySettings = [
    'proxy_client_headers' => ['HTTP_X_FORWARDED_FOR'],
    'proxy_host_headers' => ['HTTP_X_FORWARDED_HOST'],
    // Matomo picks the LAST X-Forwarded-For entry not listed here; without
    // these the appended gateway/Docker peers win over the client value.
    'proxy_ips' => ['172.31.0.0/24', '192.168.0.0/16'],
];
$proxyChanged = false;
foreach ($proxySettings as $key => $values) {
    $missing = array_diff($values, $general[$key] ?? []);
    if ($missing !== []) {
        $general[$key] = array_values(array_merge($general[$key] ?? [], $missing));
        $proxyChanged = true;
    }
}
if ($proxyChanged) {
    $config->General = $general;
    $config->forceSave();
    say('enabled proxy client-IP settings (X-Forwarded-For + trusted proxy ranges)');
} else {
    say('proxy client-IP settings already configured');
}

// 7. Geolocation: install the free DB-IP City Lite database (no account needed)
// and select the GeoIP2 (PHP) provider so those IPs resolve to cities. The
// download (~100 MB) happens on the first run only; a failure is a warning, not
// a fatal error — the stack must come up even offline.
$geoDbFile = ROOT . '/misc/DBIP-City.mmdb';
if (!is_file($geoDbFile)) {
    $months = [date('Y-m'), date('Y-m', strtotime('first day of last month'))];
    foreach ($months as $month) {
        $url = "https://download.db-ip.com/free/dbip-city-lite-{$month}.mmdb.gz";
        say("downloading GeoIP database {$url} ...");
        if (download_geoip_db($url, $geoDbFile)) {
            say('GeoIP database installed at misc/DBIP-City.mmdb');
            break;
        }
    }
    if (!is_file($geoDbFile)) {
        fwrite(STDERR, "[matomo-sidecar] WARNING: could not download a valid DB-IP City Lite; geolocation stays on the default provider\n");
    }
} else {
    say('GeoIP database already present');
}

if (is_file($geoDbFile)) {
    Access::doAsSuperUser(function () {
        if (LocationProvider::getCurrentProviderId() !== 'geoip2php') {
            LocationProvider::setCurrentProvider('geoip2php');
            say("location provider set to 'geoip2php'");
        } else {
            say("location provider already 'geoip2php'");
        }
    });
}

// Apply component/dimension DB updates via Matomo's own updater — createTables()
// leaves the log-table dimension columns out, so without this the app shows
// "database upgrade required". Delegated to the console updater; idempotent.
say('running database updater...');
$updateExit = 0;
passthru(PHP_BINARY . ' ' . escapeshellarg(ROOT . '/console') . ' core:update --yes --no-interaction 2>&1', $updateExit);
if ($updateExit !== 0) {
    fwrite(STDERR, "[matomo-sidecar] core:update failed (exit {$updateExit})\n");
    exit($updateExit);
}

// The sidecar wrote the whole tree as root (app copy, config.ini.php, GeoIP DB).
// On a Linux host the Apache user (www-data) then can't create its tmp/cache dirs
// and every request 500s — so hand the tree to www-data now. Docker Desktop remaps
// bind-mount ownership, so a local run never needs this; it's a no-op there.
say('setting web-root ownership to www-data...');
exec('chown -R www-data:www-data ' . escapeshellarg(ROOT), $chownOut, $chownExit);
if ($chownExit !== 0) {
    fwrite(STDERR, '[matomo-sidecar] WARNING: chown failed: ' . implode(' ', $chownOut) . "\n");
}

say('done.');
