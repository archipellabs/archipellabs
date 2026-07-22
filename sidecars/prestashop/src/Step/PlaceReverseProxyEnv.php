<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Writes the reverse-proxy / HTTPS-on-localhost .env override (PS_TRUSTED_PROXIES,
 * feature flags) into the web root once the install is up. Done from the sidecar
 * rather than a direct bind-mount because Docker cannot create the nested
 * /var/www/html/.env mountpoint on a fresh/empty volume.
 */
final class PlaceReverseProxyEnv extends BaseStep
{
    private const SOURCE = '/opt/sidecar/resources/webroot.env';

    public function description(): string
    {
        return 'Write the reverse-proxy / HTTPS .env override into the web root.';
    }

    public function isApplied(Context $ctx): bool
    {
        if (!is_file(self::SOURCE)) {
            return true;
        }
        $target = $this->targetPath($ctx);

        return is_file($target) && file_get_contents($target) === file_get_contents(self::SOURCE);
    }

    public function apply(Context $ctx): void
    {
        if (!is_file(self::SOURCE)) {
            $ctx->log->warn('No .env override mounted at ' . self::SOURCE . '; skipping.');

            return;
        }

        $target = $this->targetPath($ctx);
        if (!copy(self::SOURCE, $target)) {
            throw new \RuntimeException('Failed to copy .env override to ' . $target);
        }

        $ctx->log->info('Placed reverse-proxy .env at ' . $target);
    }

    private function targetPath(Context $ctx): string
    {
        return $ctx->config->psRootDir() . '/.env';
    }
}
