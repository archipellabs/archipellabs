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
    ) {
    }

    public function isInstalled(): bool
    {
        return !is_file($this->rootDir . '/' . $this->installFolder . '/index_cli.php')
            && is_file($this->rootDir . '/app/config/parameters.php');
    }

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
