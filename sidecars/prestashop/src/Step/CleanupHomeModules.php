<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Strips the default demo blocks off the storefront's home (and top) so only the
 * TimberWorks layout remains. Modules stay installed — they are just unhooked, so
 * the change is reversible. Idempotent: a module already off a hook is left alone.
 */
final class CleanupHomeModules extends BaseStep
{
    /** @var array<string, list<string>> module name => hooks to detach it from */
    private const REMOVE = [
        'ps_imageslider' => ['displayHome'],
        'ps_customtext' => ['displayHome'],
        'ps_banner' => ['displayHome'],
        'ps_newproducts' => ['displayHome'],
        'ps_bestsellers' => ['displayHome'],
        'ps_specials' => ['displayHome'],
        'psxmarketingwithgoogle' => ['displayTop'],
    ];

    public function description(): string
    {
        return 'Remove default demo blocks from the storefront home/top.';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();

        foreach (self::REMOVE as $name => $hooks) {
            $module = \Module::getInstanceByName($name);
            if (!$module || !$module->id) {
                $ctx->log->info("skip {$name} (not installed)");
                continue;
            }

            foreach ($hooks as $hook) {
                if (!$module->isRegisteredInHook($hook)) {
                    $ctx->log->info("{$name}: already off {$hook}");
                    continue;
                }

                // unregisterHook resolves the hook name the same way
                // isRegisteredInHook does (Hook::getIdByName), so detection and
                // removal stay consistent.
                $module->unregisterHook($hook);
                $ctx->log->info("unhooked {$name} from {$hook}");
            }
        }
    }
}
