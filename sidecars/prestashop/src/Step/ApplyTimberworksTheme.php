<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;
use Archipel\Provisioning\Kernel\Filesystem;

/**
 * Installs and enables the TimberWorks child theme — a Hummingbird child that
 * only ships branding overrides (assets/css/custom.css). Idempotent: the source
 * is re-synced every run (so CSS edits propagate) and the theme is enabled only
 * when it isn't already active.
 */
final class ApplyTimberworksTheme extends BaseStep
{
    private const THEME = 'timberworks';
    private const PARENT = 'hummingbird';
    private const SOURCE = '/opt/sidecar/resources/themes/' . self::THEME;

    public function description(): string
    {
        return 'Install + enable the TimberWorks child theme (branding overrides).';
    }

    public function apply(Context $ctx): void
    {
        // Boot the core up front so native classes (Shop, ...) are autoloadable;
        // the file sync below is pure filesystem and doesn't need it.
        $ctx->prestashop->boot();

        $root = $ctx->config->psRootDir();
        $dst = $root . '/themes/' . self::THEME;
        $fs = new Filesystem();

        $fs->copyDir(self::SOURCE, $dst);
        $ctx->log->info("Synced child theme to {$dst}");

        $this->ensurePreview($dst, $root . '/themes/' . self::PARENT . '/preview.png');

        // Drop the combined CSS cache (CCC) so edited custom.css is rebuilt on the
        // next request even when the theme is already active, and the compiled
        // Smarty templates so edited .tpl files recompile.
        $this->clearCssCache($dst, $ctx);
        $fs->purgeSmarty($root);

        $active = (new \Shop(1))->theme_name;
        if ($active === self::THEME) {
            $ctx->log->info('Theme already active');

            return;
        }

        $ctx->console->run(['prestashop:theme:enable', self::THEME]);
        $ctx->log->info('Enabled theme ' . self::THEME);
    }

    private function ensurePreview(string $themeDir, string $parentPreview): void
    {
        $preview = $themeDir . '/preview.png';
        if (!is_file($preview) && is_file($parentPreview)) {
            copy($parentPreview, $preview);
        }
    }

    private function clearCssCache(string $themeDir, Context $ctx): void
    {
        $cacheDir = $themeDir . '/assets/cache';
        if (!is_dir($cacheDir)) {
            return;
        }
        $removed = 0;
        foreach (glob($cacheDir . '/*.css') ?: [] as $file) {
            if (@unlink($file)) {
                $removed++;
            }
        }
        if ($removed > 0) {
            $ctx->log->info("Cleared {$removed} combined CSS cache file(s)");
        }
    }
}
