<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Storefront catalogue-display tweaks. Currently: disable the automatic "New"
 * product flag — with a freshly seeded catalogue every product would otherwise
 * be flagged "New" (all created within PS_NB_DAYS_NEW_PRODUCT days). Idempotent.
 */
final class ConfigureCatalogDisplay extends BaseStep
{
    public function description(): string
    {
        return 'Catalogue display: disable the automatic "New" product flag.';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();

        // 0 days → no product is ever considered "new" (no New badge, empty
        // new-products list). The catalogue isn't a feed of fresh arrivals here.
        \Configuration::updateValue('PS_NB_DAYS_NEW_PRODUCT', 0);
        $ctx->log->info('Disabled "New" flag (PS_NB_DAYS_NEW_PRODUCT = 0)');
    }
}
