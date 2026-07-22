<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;
use Archipel\Provisioning\Kernel\Filesystem;

/**
 * Syncs + installs the custom PrestaShop modules shipped under resources/modules/.
 * Each is copied into the volume's modules/ (so edits propagate) and installed via
 * the console when not already installed. Idempotent.
 */
final class InstallCustomModules extends BaseStep
{
    private const SOURCE = '/opt/sidecar/resources/modules';

    public function description(): string
    {
        return 'Sync + install the custom PrestaShop modules (resources/modules/).';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();
        if (!is_dir(self::SOURCE)) {
            return;
        }

        $fs = new Filesystem();
        foreach (glob(self::SOURCE . '/*', GLOB_ONLYDIR) ?: [] as $dir) {
            $name = basename($dir);
            $fs->copyDir($dir, $ctx->config->psRootDir() . '/modules/' . $name);

            if (\Module::isInstalled($name)) {
                $ctx->log->info("module {$name} already installed (synced)");
                continue;
            }
            $ctx->console->run(['prestashop:module', 'install', $name]);
            $ctx->log->info("installed module {$name}");
        }
    }
}
