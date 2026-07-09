<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Storefront languages for the North-America site: English (US) + French, with
 * English (US) as default, and the stray English-GB (from the install) removed
 * entirely (deactivating left it lingering in the BO product language tabs).
 * Installing French downloads its PrestaShop language pack (UI translations).
 * Idempotent.
 */
final class ConfigureLanguages extends BaseStep
{
    private const DEFAULT_ISO = 'en'; // English (US), id 1
    private const FRENCH_ISO = 'fr';
    private const FRENCH_LOCALE = 'fr-FR'; // translation catalogs dir
    private const REMOVE_ISOS = ['gb']; // English GB, ships with the install

    public function description(): string
    {
        return 'Enable English (US) + French, remove English-GB, default English.';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();
        $root = $ctx->config->psRootDir();

        if (!\Language::getIdByIso(self::FRENCH_ISO, true)) {
            // checkAndAddLanguage raises PS-internal notices during the add.
            $added = $ctx->quietly(fn () => \Language::checkAndAddLanguage(self::FRENCH_ISO));
            if (!$added) {
                throw new \RuntimeException('Failed to add the French language');
            }
            $ctx->log->info('Added French language');
        }

        $this->installTranslationPack($ctx, $root);

        $this->setActive($ctx, self::DEFAULT_ISO, true);
        $this->setActive($ctx, self::FRENCH_ISO, true);
        foreach (self::REMOVE_ISOS as $iso) {
            $this->removeLanguage($ctx, $iso);
        }

        $defaultId = (int) \Language::getIdByIso(self::DEFAULT_ISO, true);
        if ($defaultId) {
            \Configuration::updateValue('PS_LANG_DEFAULT', $defaultId);
            $ctx->log->info('Default language = ' . self::DEFAULT_ISO . " (id={$defaultId})");
        }
    }

    private function installTranslationPack(Context $ctx, string $root): void
    {
        $dir = $root . '/translations/' . self::FRENCH_LOCALE;
        if (is_dir($dir)) {
            $ctx->log->info('French translation pack already present');

            return;
        }

        // Downloads + extracts the .xlf catalogs (the UI translations). Its final
        // updateMultilangTables() step needs the Symfony container (absent in this
        // CLI bootstrap) and throws AFTER the catalogs are written — so the UI
        // translations install regardless; we tolerate that specific failure.
        try {
            $ctx->quietly(fn () => \Language::downloadAndInstallLanguagePack(self::FRENCH_ISO));
        } catch (\Throwable $e) {
            // expected in CLI: container-less DB-content translation step
        }

        if (is_dir($dir)) {
            $ctx->log->info('Installed French translation pack (UI)');
        } else {
            $ctx->log->warn('French translation pack did not install (check network)');
        }
    }

    private function setActive(Context $ctx, string $iso, bool $active): void
    {
        $id = (int) \Language::getIdByIso($iso, true);
        if (!$id) {
            return;
        }
        $language = new \Language($id);
        if ((bool) $language->active === $active) {
            return;
        }
        $language->active = $active;
        $language->save();
        $ctx->log->info(($active ? 'enabled' : 'disabled') . " language {$iso} (id={$id})");
    }

    private function removeLanguage(Context $ctx, string $iso): void
    {
        $id = (int) \Language::getIdByIso($iso, true);
        if (!$id) {
            return; // already removed
        }
        $language = new \Language($id);
        if (!\Validate::isLoadedObject($language)) {
            return;
        }
        // Full delete (not just deactivate): Language::delete drops the ps_lang
        // row, every *_lang row for it, and its translation files — so it stops
        // showing in the BO product language tabs.
        $deleted = $ctx->quietly(fn () => $language->delete());
        $ctx->log->info(($deleted ? 'removed' : 'could not remove') . " language {$iso} (id={$id})");
    }
}
