<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Replaces blockreassurance's three placeholder trust blocks ("Security /
 * Delivery / Return policy — (edit with the Customer Reassurance module)") with
 * real bilingual TimberWorks copy, scoped to our reality (bank-wire payment,
 * US + Canada shipping). Content only — these blocks display trust signals, they
 * enforce nothing. SQL on the module's own table (its ObjectModel is a module
 * class, not autoloaded in the sidecar boot). Idempotent.
 */
final class ConfigureReassurance extends BaseStep
{
    /** id_psreassurance => iso => [title, description]. Block ids/icons are the install defaults: 1 security, 2 delivery, 3 returns. */
    private const BLOCKS = [
        1 => [
            'en' => ['Secure payment', 'Pay safely by bank wire; every order is confirmed before we ship.'],
            'fr' => ['Paiement sécurisé', 'Réglez en toute sécurité par virement ; chaque commande est confirmée avant expédition.'],
        ],
        2 => [
            'en' => ['Shipping across the US & Canada', 'Tracked delivery on all wood materials and kits.'],
            'fr' => ['Livraison aux États-Unis et au Canada', 'Livraison suivie sur tous nos bois et kits.'],
        ],
        3 => [
            'en' => ['30-day returns', 'Not the right fit? Return stock items within 30 days.'],
            'fr' => ['Retours sous 30 jours', 'Pas le bon produit ? Retournez les articles en stock sous 30 jours.'],
        ],
    ];

    public function description(): string
    {
        return 'Fill the reassurance blocks with real bilingual content.';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();
        $db = $ctx->db();

        $rows = 0;
        foreach (\Language::getLanguages(false) as $lang) {
            $langId = (int) $lang['id_lang'];
            $iso = $lang['iso_code'];
            foreach (self::BLOCKS as $blockId => $byIso) {
                [$title, $description] = $byIso[$iso] ?? $byIso['en'];
                $db->execute(
                    'UPDATE ' . _DB_PREFIX_ . 'psreassurance_lang'
                    . ' SET title = "' . pSQL($title) . '", description = "' . pSQL($description) . '"'
                    . ' WHERE id_psreassurance = ' . (int) $blockId . ' AND id_lang = ' . $langId
                );
                $rows++;
            }
        }
        $ctx->log->info("Reassurance blocks filled ({$rows} lang rows across " . \count(self::BLOCKS) . ' blocks)');
    }
}
