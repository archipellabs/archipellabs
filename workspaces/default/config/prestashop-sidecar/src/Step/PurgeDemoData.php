<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Setup-time purge of the PrestaShop install's demo data — the correction for
 * the fact that the official Docker image can only install *with* demo fixtures
 * (a clean Shopify-style store would have nothing to purge). It clears:
 *   - the demo orders (owned by the demo customer "John DOE"), and
 *   - the demo catalogue (products, categories, features, attribute groups,
 *     suppliers) — the same scope the simulator's old catalog-delete covered,
 *     now moved here so the simulator only ever does an additive sync.
 *
 * Gated on the demo customer's existence (pub@prestashop.com), which is the
 * signature of an un-purged demo install, and the customer is deleted LAST as
 * the sentinel. So the step runs once on a fresh install and is a permanent
 * no-op afterwards — it never touches the PIM catalogue the simulator syncs nor
 * the orders the simulator generates.
 */
final class PurgeDemoData extends BaseStep
{
    private const DEMO_CUSTOMER_EMAIL = 'pub@prestashop.com';
    private const PROTECTED_CATEGORY_IDS = [1, 2]; // Root + Home — never delete.

    /** Order child tables keyed by id_order, cleared before ps_orders. */
    private const ORDER_CHILD_TABLES = [
        'order_detail', 'order_history', 'order_carrier', 'order_cart_rule',
        'order_invoice_payment', 'order_invoice', 'order_slip', 'order_return',
        'message', 'customer_thread', 'shipment',
    ];

    public function description(): string
    {
        return 'Purge install demo data (orders + catalogue) on a fresh install.';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();
        $db = $ctx->db();

        $customerId = (int) $db->getValue(
            'SELECT id_customer FROM ' . _DB_PREFIX_ . 'customer'
            . ' WHERE email = "' . pSQL(self::DEMO_CUSTOMER_EMAIL) . '"'
        );
        if (!$customerId) {
            $ctx->log->info(
                'Demo customer (' . self::DEMO_CUSTOMER_EMAIL . ') absent — '
                . 'already purged or non-demo install; nothing to do'
            );

            return;
        }

        $this->purgeDemoOrders($ctx, $db, $customerId);
        $this->purgeDemoCatalog($ctx, $db);
        $this->deleteDemoCustomer($ctx, $customerId); // sentinel — closes the gate
    }

    private function purgeDemoOrders(Context $ctx, \Db $db, int $customerId): void
    {
        $rows = $db->executeS(
            'SELECT id_order FROM ' . _DB_PREFIX_ . 'orders WHERE id_customer = ' . $customerId
        ) ?: [];
        $ids = array_map('intval', array_column($rows, 'id_order'));
        if (!$ids) {
            $ctx->log->info('No demo orders to purge');

            return;
        }
        $in = implode(',', $ids);

        // Grandchildren first (keyed off the child rows, not id_order).
        $db->execute('DELETE FROM ' . _DB_PREFIX_ . 'order_detail_tax WHERE id_order_detail IN (SELECT id_order_detail FROM ' . _DB_PREFIX_ . 'order_detail WHERE id_order IN (' . $in . '))');
        $db->execute('DELETE FROM ' . _DB_PREFIX_ . 'order_slip_detail WHERE id_order_slip IN (SELECT id_order_slip FROM ' . _DB_PREFIX_ . 'order_slip WHERE id_order IN (' . $in . '))');
        $db->execute('DELETE FROM ' . _DB_PREFIX_ . 'order_invoice_tax WHERE id_order_invoice IN (SELECT id_order_invoice FROM ' . _DB_PREFIX_ . 'order_invoice WHERE id_order IN (' . $in . '))');
        $db->execute('DELETE FROM ' . _DB_PREFIX_ . 'customer_message WHERE id_customer_thread IN (SELECT id_customer_thread FROM ' . _DB_PREFIX_ . 'customer_thread WHERE id_order IN (' . $in . '))');

        foreach (self::ORDER_CHILD_TABLES as $table) {
            $db->execute('DELETE FROM ' . _DB_PREFIX_ . $table . ' WHERE id_order IN (' . $in . ')');
        }
        $db->execute('DELETE FROM ' . _DB_PREFIX_ . 'orders WHERE id_order IN (' . $in . ')');

        $ctx->log->info('Purged ' . \count($ids) . ' demo order(s)');
    }

    private function purgeDemoCatalog(Context $ctx, \Db $db): void
    {
        // Products first (they reference categories/features/attributes), then
        // the rest. Deletes go through the PrestaShop model classes so each one
        // cascades cleanly (product images, *_lang rows, associations, option
        // values, feature values, …) instead of clearing dozens of tables by hand.
        $catIds = 'id_category NOT IN (' . implode(',', self::PROTECTED_CATEGORY_IDS) . ')';
        $report = [
            'products' => $this->deleteObjects($ctx, $db,'product', 'id_product', \Product::class),
            'categories' => $this->deleteObjects($ctx, $db,'category', 'id_category', \Category::class, $catIds),
            'features' => $this->deleteObjects($ctx, $db,'feature', 'id_feature', \Feature::class),
            'attribute_groups' => $this->deleteObjects($ctx, $db,'attribute_group', 'id_attribute_group', \AttributeGroup::class),
            'suppliers' => $this->deleteObjects($ctx, $db,'supplier', 'id_supplier', \Supplier::class),
        ];
        $summary = implode(', ', array_map(
            static fn (string $k, int $v): string => "{$v} {$k}",
            array_keys($report),
            array_values($report),
        ));
        $ctx->log->info('Purged demo catalogue: ' . $summary);
    }

    /**
     * @param class-string<\ObjectModel> $class
     */
    private function deleteObjects(Context $ctx, \Db $db, string $table, string $pk, string $class, string $where = ''): int
    {
        $sql = 'SELECT ' . $pk . ' FROM ' . _DB_PREFIX_ . $table . ($where ? ' WHERE ' . $where : '');
        $rows = $db->executeS($sql) ?: [];

        return $ctx->quietly(static function () use ($rows, $pk, $class): int {
            $deleted = 0;
            foreach ($rows as $row) {
                $object = new $class((int) $row[$pk]);
                // A cascading delete may have already removed a child (e.g. a
                // sub-category); skip anything no longer loadable.
                if (\Validate::isLoadedObject($object) && $object->delete()) {
                    $deleted++;
                }
            }

            return $deleted;
        });
    }

    private function deleteDemoCustomer(Context $ctx, int $customerId): void
    {
        $customer = new \Customer($customerId);
        if (!\Validate::isLoadedObject($customer)) {
            return;
        }
        $deleted = $ctx->quietly(fn () => $customer->delete());
        $ctx->log->info(($deleted ? 'removed' : 'could not remove') . ' demo customer #' . $customerId);
    }
}
