<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Kernel;

/**
 * Boots the PrestaShop core from the mounted web root so steps can use native
 * classes (Configuration, WebserviceKey, Db, ...). Booting is idempotent.
 */
final class PrestaShop
{
    private bool $booted = false;

    public function __construct(
        private readonly string $rootDir,
        private readonly string $installFolder,
        private readonly Logger $log,
        private readonly string $internalHost = 'prestashop',
    ) {
    }

    /**
     * Installed means THE SCHEMA IS USABLE, which only the database can answer.
     *
     * Every file-based marker lies at least once. The install folder used to be
     * deleted on success and now survives, so testing for its absence never
     * succeeds and provisioning times out on a cold start. `install.lock` and
     * `parameters.php` both appear *before* the tables are created, so testing
     * for those starts provisioning too early — the first step then dies on
     * `foreach() on false` inside Shop.php, because `ps_shop` does not exist yet.
     *
     * Both failures are ugly in the same way: they strand `matomo`, the gateway
     * and `sftp`, which are gated on this container completing.
     */
    public function isInstalled(): bool
    {
        return is_file($this->rootDir . '/app/config/parameters.php')
            && $this->schemaReady()
            && $this->appAnswers();
    }

    /**
     * The web container serves a page — the only honest proof that the
     * application BOOTS, rather than merely that its tables exist.
     *
     * Both weaker checks were tried and both start provisioning too early. The
     * installer creates `ps_shop` well before it writes `PS_LANG_DEFAULT`, so a
     * schema check lets the first step through and PrestaShop dies constructing
     * its Translator with a null locale. And because the two containers share
     * /var/www/html, starting before the web container has warmed its Symfony
     * cache makes `bin/console` read a half-written container.
     *
     * A served response is after all of it.
     */
    private function appAnswers(): bool
    {
        $context = stream_context_create([
            'http' => [
                'method' => 'HEAD',
                'timeout' => 5,
                // A redirect to the canonical domain is a perfectly good answer.
                'follow_location' => 0,
                'ignore_errors' => true,
            ],
        ]);

        $handle = @fopen('http://' . $this->internalHost . '/', 'r', false, $context);
        if ($handle === false) {
            return false;
        }
        $meta = stream_get_meta_data($handle);
        fclose($handle);

        foreach ($meta['wrapper_data'] ?? [] as $header) {
            if (preg_match('#^HTTP/\S+\s+([23]\d\d)#', (string) $header) === 1) {
                return true;
            }
        }

        return false;
    }

    /** Can we connect with the installer's own credentials and read a core table? */
    private function schemaReady(): bool
    {
        $config = @include $this->rootDir . '/app/config/parameters.php';
        $params = $config['parameters'] ?? null;

        if (!\is_array($params) || !isset($params['database_host'], $params['database_name'])) {
            return false;
        }

        // PDO, not mysqli: this image ships pdo_mysql and no mysqli at all.
        $dsn = sprintf(
            'mysql:host=%s;port=%d;dbname=%s',
            $params['database_host'],
            (int) ($params['database_port'] ?? 3306) ?: 3306,
            $params['database_name']
        );

        try {
            $pdo = new \PDO(
                $dsn,
                $params['database_user'] ?? '',
                $params['database_password'] ?? '',
                [\PDO::ATTR_ERRMODE => \PDO::ERRMODE_EXCEPTION, \PDO::ATTR_TIMEOUT => 3]
            );

            // ps_shop specifically: it is what the first provisioning step reads,
            // and it is populated late enough to stand for "the installer has
            // finished". A refused connection and a missing table are both just
            // "not yet", which is the normal case on the way up.
            $table = ($params['database_prefix'] ?? 'ps_') . 'shop';

            return (bool) $pdo->query('SELECT 1 FROM `' . $table . '` LIMIT 1')->fetchColumn();
        } catch (\PDOException) {
            return false;
        }
    }

    /**
     * A cold start copies the whole application directory out of the image before
     * the installer even runs, so this budget is for minutes, not seconds. If it
     * is ever exceeded, measure before raising it — the last time it timed out
     * the cause was an emulated JVM eating the CPU, not a slow copy.
     */
    public function waitUntilInstalled(int $attempts = 60, int $sleepSeconds = 5): void
    {
        for ($i = 1; $i <= $attempts; $i++) {
            if ($this->isInstalled()) {
                $this->log->success("PrestaShop installation detected (attempt {$i}/{$attempts})");

                return;
            }
            $this->log->info("waiting for PrestaShop installation ({$i}/{$attempts})...");
            sleep($sleepSeconds);
        }

        throw new \RuntimeException('Timed out waiting for the PrestaShop installation to complete');
    }

    public function boot(): void
    {
        if ($this->booted) {
            return;
        }

        if (!\defined('_PS_ROOT_DIR_')) {
            \define('_PS_ROOT_DIR_', $this->rootDir);
        }
        $_SERVER['HTTP_HOST'] = 'localhost';
        $_SERVER['SERVER_NAME'] = 'localhost';
        $_SERVER['SERVER_PORT'] = 443;
        $_SERVER['HTTPS'] = 'on';

        require_once $this->rootDir . '/config/config.inc.php';

        $this->booted = true;
    }

    public function db(): \Db
    {
        $this->boot();

        return \Db::getInstance();
    }
}
