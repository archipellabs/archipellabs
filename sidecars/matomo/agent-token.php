<?php

declare(strict_types=1);

/**
 * Creates the view-only analyst account an agent investigates with.
 *
 * A SEPARATE PROCESS from install.php, and that is the whole point. Matomo stores
 * a token as a salted hash, and `Config` is a singleton: the installer holds the
 * salt it read at boot, while its own later writes settle a different one on
 * disk. A token created inside that process is hashed with the stale salt and
 * verified against the final one, so it authenticates as "invalid or expired"
 * while looking perfectly correct in the database. A fresh process reads
 * config.ini.php as it now stands and the two agree.
 *
 * Idempotent in three parts: the user, its access, and the token are each created
 * only if absent.
 */

use Piwik\Access;
use Piwik\Application\Environment;
use Piwik\Date;
use Piwik\Plugin\Manager as PluginManager;
use Piwik\Plugins\UsersManager\API as UsersManagerApi;
use Piwik\Plugins\UsersManager\Model as UsersManagerModel;

const ROOT = '/var/www/html';

function say(string $msg): void
{
    fwrite(STDOUT, '[matomo-agent] ' . $msg . PHP_EOL);
}

function env(string $key, string $default = ''): string
{
    $value = getenv($key);

    return $value === false || $value === '' ? $default : $value;
}

$login = env('MATOMO_AGENT_LOGIN', 'agent');
$password = env('MATOMO_AGENT_PASSWORD', '');
$email = env('MATOMO_AGENT_EMAIL', 'agent@timberworks.test');
$token = env('MATOMO_AGENT_TOKEN', '');

if ($token === '' || $password === '') {
    say('MATOMO_AGENT_TOKEN/PASSWORD not set — skipping the analyst account');
    exit(0);
}

define('PIWIK_INCLUDE_PATH', ROOT);
define('PIWIK_USER_PATH', ROOT);
define('PIWIK_DOCUMENT_ROOT', ROOT);
require_once ROOT . '/core/bootstrap.php';

$environment = new Environment(null);
$environment->init();
PluginManager::getInstance()->loadActivatedPlugins();

try {
    Access::doAsSuperUser(function () use ($login, $password, $email, $token) {
        $users = UsersManagerApi::getInstance();
        $model = new UsersManagerModel();

        if (!$model->getUser($login)) {
            $users->addUser($login, $password, $email);
            say("created analyst user '{$login}'");
        } else {
            say("analyst user '{$login}' already exists");
        }

        // Re-applied every run: cheap, and it repairs an account changed by hand.
        $users->setUserAccess($login, 'view', [1]);

        // Matomo stores only a salted hash, so existence is checked by hashing
        // the token and looking for THAT.
        if (in_array($model->hashTokenAuth($token), $model->getAllHashedTokensForLogins([$login]), true)) {
            say("analyst token already present for '{$login}'");

            return;
        }

        // PLAINTEXT here: addTokenAuth hashes internally. Passing a pre-hashed
        // value stores hash(hash(token)), which no login can ever reproduce — the
        // row looks perfectly normal and authentication answers "invalid or
        // expired", which sends you hunting for a salt problem that isn't there.
        $model->addTokenAuth($login, $token, 'agent investigation token', Date::now()->getDatetime());
        say("created analyst API token for '{$login}'");
    });
} catch (\Throwable $e) {
    fwrite(STDERR, '[matomo-agent] ERROR: ' . $e->getMessage() . "\n");
    exit(1);
}

say('done.');
