<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Installs the TimberWorks header logo and sizes it from the image's real aspect
 * ratio (the default config keeps a different ratio and would squash it).
 */
final class SetShopLogo extends BaseStep
{
    private const SOURCE = '/opt/sidecar/resources/img/timberworks-logo.png';
    private const LOGO_FILE = 'timberworks-logo.png';
    private const DISPLAY_HEIGHT = 45;

    public function description(): string
    {
        return 'Install the TimberWorks shop logo and set its display size.';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();

        if (!is_file(self::SOURCE)) {
            throw new \RuntimeException('Logo source not found: ' . self::SOURCE);
        }

        $dst = $ctx->config->psRootDir() . '/img/' . self::LOGO_FILE;
        if (!copy(self::SOURCE, $dst)) {
            throw new \RuntimeException("Failed to copy logo to {$dst}");
        }

        [$width, $height] = getimagesize($dst);
        $displayHeight = self::DISPLAY_HEIGHT;
        $displayWidth = (int) round($width * ($displayHeight / $height));

        \Configuration::updateValue('PS_LOGO', self::LOGO_FILE);
        \Configuration::updateValue('SHOP_LOGO_WIDTH', $displayWidth);
        \Configuration::updateValue('SHOP_LOGO_HEIGHT', $displayHeight);

        $ctx->log->info('Logo set to ' . self::LOGO_FILE . " ({$displayWidth}x{$displayHeight})");
    }
}
