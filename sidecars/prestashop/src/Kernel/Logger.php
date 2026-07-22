<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Kernel;

final class Logger
{
    public function info(string $message): void
    {
        $this->write(STDOUT, '--', $message);
    }

    public function success(string $message): void
    {
        $this->write(STDOUT, 'OK', $message);
    }

    public function warn(string $message): void
    {
        $this->write(STDERR, 'WARN', $message);
    }

    public function error(string $message): void
    {
        $this->write(STDERR, 'ERR', $message);
    }

    /**
     * @param resource $stream
     */
    private function write($stream, string $prefix, string $message): void
    {
        fwrite($stream, sprintf('[%s] %s%s', $prefix, $message, PHP_EOL));
    }
}
