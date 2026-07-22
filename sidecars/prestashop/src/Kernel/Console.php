<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Kernel;

/**
 * Runs a PrestaShop Symfony console command in a subprocess. Used for the things
 * only the console exposes (module install, api-client create, ...). No external
 * dependency: a thin proc_open wrapper, so it cannot clash with the Symfony
 * version PrestaShop bundles.
 */
final class Console
{
    public function __construct(
        private readonly string $rootDir,
        private readonly Logger $log,
    ) {
    }

    /**
     * @param list<string> $args arguments after `bin/console`
     *
     * @return string the command stdout
     */
    public function run(array $args): string
    {
        $command = array_merge(['php', 'bin/console'], $args);
        $this->log->info('console: ' . implode(' ', $args));

        $process = proc_open(
            $command,
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            $this->rootDir,
        );
        if (!\is_resource($process)) {
            throw new \RuntimeException('Failed to start bin/console');
        }

        $stdout = stream_get_contents($pipes[1]) ?: '';
        $stderr = stream_get_contents($pipes[2]) ?: '';
        fclose($pipes[1]);
        fclose($pipes[2]);
        $exitCode = proc_close($process);

        if ($exitCode !== 0) {
            throw new \RuntimeException(sprintf(
                'bin/console %s failed (exit %d): %s',
                implode(' ', $args),
                $exitCode,
                trim($stderr !== '' ? $stderr : $stdout),
            ));
        }

        return $stdout;
    }
}
