<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Installs + configures the Matomo tracking module (tec_matomo — Matomo analytics
 * with ecommerce tracking, MIT, github.com/ArteInfoRM/tec_matomo).
 *
 * The module is fetched at provision time from its PINNED GitHub release rather
 * than vendored, keeping third-party code out of the repo while staying pinned +
 * reproducible. Settings (Matomo URL, site id, optional API token) come from the
 * environment so they can differ per deployment. Idempotent: the download +
 * console install are skipped once the module is present, and the settings are
 * plain Configuration values that are safe to re-apply.
 *
 * Requires: the Matomo instance reachable at MATOMO_URL over HTTPS from the
 * shopper's browser (see the gateway vhost), and a Matomo site created as the
 * matching MATOMO_SITE_ID (one-time Matomo bootstrap).
 */
final class InstallMatomo extends BaseStep
{
    private const MODULE = 'tec_matomo';
    private const VERSION = '1.2.0';
    private const RELEASE_ZIP =
        'https://github.com/ArteInfoRM/tec_matomo/releases/download/v1.2.0/tec_matomo-1.2.0.zip';

    public function description(): string
    {
        return 'Install + configure the Matomo tracking module (tec_matomo).';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();

        $modulesDir = $ctx->config->psRootDir() . '/modules';
        if (!is_dir($modulesDir . '/' . self::MODULE)) {
            $this->fetchRelease($ctx, $modulesDir);
        }

        if (!\Module::isInstalled(self::MODULE)) {
            $ctx->console->run(['prestashop:module', 'install', self::MODULE]);
            $ctx->log->info('installed module ' . self::MODULE);
        } else {
            $ctx->log->info('module ' . self::MODULE . ' already installed');
        }

        $this->configure($ctx);
    }

    /** Download the pinned release zip and extract it into modules/. */
    private function fetchRelease(Context $ctx, string $modulesDir): void
    {
        $ctx->log->info('fetching ' . self::MODULE . ' v' . self::VERSION . ' from GitHub');

        $ch = curl_init(self::RELEASE_ZIP);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true, // release asset redirects to a CDN
            CURLOPT_FAILONERROR => true,
            CURLOPT_TIMEOUT => 60,
        ]);
        $data = curl_exec($ch);
        $error = curl_error($ch);
        curl_close($ch);
        if ($data === false) {
            throw new \RuntimeException('Failed to download ' . self::MODULE . ': ' . $error);
        }

        $tmp = sys_get_temp_dir() . '/' . self::MODULE . '-' . self::VERSION . '.zip';
        if (file_put_contents($tmp, $data) === false) {
            throw new \RuntimeException('Failed to write ' . $tmp);
        }

        $zip = new \ZipArchive();
        if ($zip->open($tmp) !== true) {
            throw new \RuntimeException('Failed to open ' . $tmp);
        }
        // The release zip already contains a top-level tec_matomo/ folder, so it
        // extracts straight into modules/tec_matomo/.
        $zip->extractTo($modulesDir);
        $zip->close();
        @unlink($tmp);

        $ctx->log->info('extracted ' . self::MODULE . ' into modules/');
    }

    /** Point the module at our Matomo instance and enable ecommerce tracking. */
    private function configure(Context $ctx): void
    {
        // The module was just installed in a console subprocess, so this process's
        // Configuration cache predates its keys. Reload it so updateValue UPDATEs
        // the existing rows instead of failing an INSERT (which left them NULL).
        \Configuration::loadConfiguration();

        $config = $ctx->config;
        $values = [
            'TEC_MATOMO_ACTIVE' => '1',
            'TEC_MATOMO_URL' => $config->matomoUrl(),
            'TEC_MATOMO_SITEID' => $config->matomoSiteId(),
            'TEC_MATOMO_ECOMMERCE' => '1',
        ];
        if ($config->matomoToken() !== '') {
            $values['TEC_MATOMO_TOKEN'] = $config->matomoToken();
        }

        foreach ($values as $key => $value) {
            \Configuration::updateValue($key, $value);
        }

        $ctx->log->info(sprintf(
            'configured %s: url=%s siteId=%s ecommerce=on',
            self::MODULE,
            $config->matomoUrl(),
            $config->matomoSiteId(),
        ));
    }
}
