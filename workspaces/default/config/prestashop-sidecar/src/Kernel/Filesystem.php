<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Kernel;

final class Filesystem
{
    /**
     * Recursively copy a directory tree, overwriting existing files (used to sync
     * versioned theme/module sources into the PrestaShop volume).
     */
    public function copyDir(string $src, string $dst): void
    {
        if (!is_dir($src)) {
            throw new \RuntimeException("Source directory not found: {$src}");
        }
        $this->ensureDir($dst);

        $items = new \RecursiveIteratorIterator(
            new \RecursiveDirectoryIterator($src, \FilesystemIterator::SKIP_DOTS),
            \RecursiveIteratorIterator::SELF_FIRST,
        );

        foreach ($items as $item) {
            $target = $dst . '/' . $items->getSubPathname();
            if ($item->isDir()) {
                $this->ensureDir($target);
            } elseif (!copy($item->getPathname(), $target)) {
                throw new \RuntimeException("Cannot copy {$item->getPathname()} -> {$target}");
            }
        }
    }

    private function ensureDir(string $dir): void
    {
        if (!is_dir($dir) && !mkdir($dir, 0o775, true) && !is_dir($dir)) {
            throw new \RuntimeException("Cannot create directory: {$dir}");
        }
    }

    /**
     * Drop PrestaShop's compiled Smarty templates so edited .tpl files recompile
     * on the next request (templates are cached under var/cache/<env>/smarty).
     */
    public function purgeSmarty(string $psRoot): void
    {
        foreach (glob($psRoot . '/var/cache/*/smarty/{compile,cache}', GLOB_BRACE) ?: [] as $dir) {
            $this->rmDirContents($dir);
        }
    }

    private function rmDirContents(string $dir): void
    {
        if (!is_dir($dir)) {
            return;
        }
        $items = new \RecursiveIteratorIterator(
            new \RecursiveDirectoryIterator($dir, \FilesystemIterator::SKIP_DOTS),
            \RecursiveIteratorIterator::CHILD_FIRST,
        );
        foreach ($items as $item) {
            $item->isDir() ? @rmdir($item->getPathname()) : @unlink($item->getPathname());
        }
    }
}
