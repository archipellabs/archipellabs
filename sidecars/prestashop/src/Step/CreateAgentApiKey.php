<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * A second Webservice key, for an agent investigating the shop — read-only, and
 * scoped to what the question needs.
 *
 * The integration's key (ConfigureWebservice) has every method on every
 * resource, because it has to write carriers and delivery prices. Handing that
 * to an agent would make "read-only" a promise in a prompt rather than a
 * property of the credential, and the access gradient in doc/agent-org-lab.md §7
 * only means something if the boundary is enforced by the shop.
 *
 * So this key gets GET (and HEAD) and nothing else. An attempt to write comes
 * back 405 from PrestaShop rather than being caught by good behaviour.
 *
 * The scope is deliberately broader than the reference incident needs. An
 * investigator who is handed exactly the four resources that contain the answer
 * has been given the answer; the point is to leave enough room to look in the
 * wrong place first — stock, customers, products — and rule things out.
 */
final class CreateAgentApiKey extends BaseStep
{
    /**
     * Read scope for the analyst/technical roles.
     *
     * Sales and geography answer "what happened"; carriers, deliveries and zones
     * answer "why"; catalogue and stock are there to be ruled out.
     *
     * @var list<string>
     */
    private const RESOURCES = [
        // sales, and the step before a sale — a cart records which address a
        // shopper reached and whether an order ever followed, which is the only
        // place the company can see where customers stop. Shop staff see carts;
        // withholding them was the anomaly.
        'orders', 'order_details', 'order_states', 'order_histories', 'order_carriers',
        'carts',
        // who and where
        'customers', 'addresses', 'countries', 'states', 'zones',
        // shipping — where the reference incident actually lands
        'carriers', 'deliveries', 'price_ranges',
        // catalogue, so a dead end is available
        'products', 'stock_availables', 'categories', 'suppliers',
        // shop context
        'currencies', 'languages', 'shops',
    ];

    /** Read-only. HEAD is included because it is a read, and 405 on it is confusing. */
    private const METHODS = ['GET' => 1, 'HEAD' => 1];

    public function description(): string
    {
        return 'Create a read-only Webservice key for the investigating agent.';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();

        $key = $ctx->config->agentApiKey();
        if ($key === '') {
            $ctx->log->info('AGENT_API_KEY not set — skipping the agent key');

            return;
        }

        $accountId = $this->ensureKey($ctx, $key);

        $permissions = [];
        foreach (self::RESOURCES as $resource) {
            $permissions[$resource] = self::METHODS;
        }
        \WebserviceKey::setPermissionForAccount($accountId, $permissions);

        $ctx->log->info(
            'Agent key: GET/HEAD on ' . \count(self::RESOURCES) . ' resources, no write methods'
        );
    }

    private function ensureKey(Context $ctx, string $key): int
    {
        $existingId = \WebserviceKey::getIdFromKey($key);

        if ($existingId) {
            $ctx->log->info("Agent key already exists (id={$existingId})");

            return (int) $existingId;
        }

        $account = new \WebserviceKey();
        $account->key = $key;
        $account->description = 'Agent (read-only)';
        $account->active = 1;

        // ObjectModel::add() raises a PS-internal null-property notice here.
        $saved = $ctx->quietly(fn () => $account->save());

        if (!$saved) {
            throw new \RuntimeException('Failed to save the agent webservice key');
        }

        $ctx->log->info("Agent key created (id={$account->id})");

        return (int) $account->id;
    }
}
