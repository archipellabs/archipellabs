<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Kernel;

/**
 * Shared services handed to every step.
 */
final class Context
{
    public function __construct(
        public readonly Config $config,
        public readonly Logger $log,
        public readonly PrestaShop $prestashop,
        public readonly Console $console,
    ) {
    }

    public function db(): \Db
    {
        return $this->prestashop->db();
    }

    /**
     * Run $fn with PrestaShop's internal notices/warnings silenced — the legacy
     * models emit E_NOTICE/E_DEPRECATED during add()/save()/delete() in this
     * container-less CLI boot. The previous level is always restored.
     *
     * @template T
     * @param callable():T $fn
     *
     * @return T
     */
    public function quietly(callable $fn): mixed
    {
        $previous = error_reporting(E_ERROR | E_PARSE);
        try {
            return $fn();
        } finally {
            error_reporting($previous);
        }
    }

    /**
     * Build a multilang field value [id_lang => text] over every installed
     * language, picking $byIso[<iso_code>] and falling back to $byIso[$fallback].
     *
     * @param array<string, string> $byIso
     *
     * @return array<int, string>
     */
    public function localized(array $byIso, string $fallback = 'en'): array
    {
        $this->prestashop->boot();

        $out = [];
        foreach (\Language::getLanguages(false) as $lang) {
            $out[(int) $lang['id_lang']] = $byIso[$lang['iso_code']] ?? $byIso[$fallback] ?? '';
        }

        return $out;
    }
}
