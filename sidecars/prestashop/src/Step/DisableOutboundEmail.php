<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Stops PrestaShop sending mail. Idempotent.
 *
 * The shop has no transactional email channel — bank details reach the customer
 * on the payment step and the order-confirmation page instead (see
 * ConfigureCheckout). Every state change PrestaShop considers mail-worthy is
 * therefore an attempt with nowhere to go: "Payment accepted" alone fired 171 of
 * them the first time the settlement flow drained the backlog.
 *
 * The failures are harmless but they are not free — they are attempts on every
 * order transition, they land in the logs as noise that looks like a fault, and
 * with a *reachable but wrong* SMTP host they would block the request instead of
 * failing fast. Turning mail off makes "no email yet" a stated decision rather
 * than an accident of the container having no MTA.
 *
 * When transactional email becomes a real stage, this step is what gets deleted.
 */
final class DisableOutboundEmail extends BaseStep
{
    public function description(): string
    {
        return 'Disable outbound email (no transactional mail channel yet).';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();

        $current = (int) \Configuration::get('PS_MAIL_METHOD');
        if ($current === \Mail::METHOD_DISABLE) {
            $ctx->log->info('Outbound email already disabled');

            return;
        }

        \Configuration::updateValue('PS_MAIL_METHOD', \Mail::METHOD_DISABLE);
        $ctx->log->info("Outbound email disabled (PS_MAIL_METHOD {$current} → " . \Mail::METHOD_DISABLE . ')');
    }
}
