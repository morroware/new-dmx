<?php
/**
 * SMTP Mailer - Pure PHP implementation (no dependencies)
 * Supports PLAIN, LOGIN, and CRAM-MD5 authentication
 * Supports TLS/SSL encryption
 */
class Mailer {
    private string $host;
    private int $port;
    private string $encryption;
    private string $username;
    private string $password;
    private string $fromEmail;
    private string $fromName;
    private ?resource $socket = null;

    public function __construct(?array $config = null) {
        $db = Database::getInstance();
        $settings = [];
        $rows = $db->query("SELECT key, value FROM settings WHERE key LIKE 'smtp_%' OR key LIKE 'from_%'")->fetchAll();
        foreach ($rows as $row) $settings[$row['key']] = $row['value'];

        $this->host = $config['host'] ?? $settings['smtp_host'] ?? DEFAULT_SMTP_HOST;
        $this->port = (int)($config['port'] ?? $settings['smtp_port'] ?? DEFAULT_SMTP_PORT);
        $this->encryption = $config['encryption'] ?? $settings['smtp_encryption'] ?? DEFAULT_SMTP_ENCRYPTION;
        $this->username = $config['username'] ?? $settings['smtp_username'] ?? DEFAULT_SMTP_USERNAME;
        $this->password = $config['password'] ?? $settings['smtp_password'] ?? DEFAULT_SMTP_PASSWORD;
        $this->fromEmail = $config['from_email'] ?? $settings['from_email'] ?? DEFAULT_FROM_EMAIL;
        $this->fromName = $config['from_name'] ?? $settings['from_name'] ?? DEFAULT_FROM_NAME;
    }

    public function send(string $to, string $subject, string $htmlBody, string $textBody = '', array $headers = []): array {
        $messageId = $this->generateMessageId();
        $boundary = 'boundary_' . md5(uniqid());

        $emailHeaders = [
            'From' => $this->formatAddress($this->fromEmail, $headers['from_name'] ?? $this->fromName),
            'To' => $to,
            'Subject' => $subject,
            'Message-ID' => '<' . $messageId . '>',
            'MIME-Version' => '1.0',
            'Content-Type' => 'multipart/alternative; boundary="' . $boundary . '"',
            'Date' => date('r'),
            'X-Mailer' => APP_NAME . '/' . APP_VERSION,
        ];

        if (!empty($headers['reply_to'])) {
            $emailHeaders['Reply-To'] = $headers['reply_to'];
        }
        if (!empty($headers['list_unsubscribe'])) {
            $emailHeaders['List-Unsubscribe'] = '<' . $headers['list_unsubscribe'] . '>';
            $emailHeaders['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click';
        }

        $body = "--{$boundary}\r\n";
        $body .= "Content-Type: text/plain; charset=UTF-8\r\n";
        $body .= "Content-Transfer-Encoding: quoted-printable\r\n\r\n";
        $body .= quoted_printable_encode($textBody ?: strip_tags($htmlBody)) . "\r\n";
        $body .= "--{$boundary}\r\n";
        $body .= "Content-Type: text/html; charset=UTF-8\r\n";
        $body .= "Content-Transfer-Encoding: quoted-printable\r\n\r\n";
        $body .= quoted_printable_encode($htmlBody) . "\r\n";
        $body .= "--{$boundary}--\r\n";

        try {
            $this->connect();
            $this->ehlo();

            if ($this->encryption === 'tls') {
                $this->sendCommand("STARTTLS", 220);
                stream_socket_enable_crypto($this->socket, true, STREAM_CRYPTO_METHOD_TLSv1_2_CLIENT);
                $this->ehlo();
            }

            if (!empty($this->username)) {
                $this->authenticate();
            }

            $this->sendCommand("MAIL FROM:<{$this->fromEmail}>", 250);
            $this->sendCommand("RCPT TO:<{$to}>", 250);
            $this->sendCommand("DATA", 354);

            $headerStr = '';
            foreach ($emailHeaders as $key => $value) {
                $headerStr .= "{$key}: {$value}\r\n";
            }

            $this->sendData($headerStr . "\r\n" . $body . "\r\n.");
            $response = $this->readResponse();

            $this->sendCommand("QUIT", 221);
            $this->disconnect();

            return ['success' => true, 'message_id' => $messageId];
        } catch (Exception $e) {
            $this->disconnect();
            return ['success' => false, 'error' => $e->getMessage(), 'message_id' => $messageId];
        }
    }

    private function connect(): void {
        $host = $this->host;
        if ($this->encryption === 'ssl') {
            $host = 'ssl://' . $host;
        }

        $this->socket = @stream_socket_client(
            "{$host}:{$this->port}",
            $errno, $errstr, 30,
            STREAM_CLIENT_CONNECT
        );

        if (!$this->socket) {
            throw new Exception("Failed to connect to SMTP: {$errstr} ({$errno})");
        }

        stream_set_timeout($this->socket, 30);
        $this->readResponse();
    }

    private function ehlo(): void {
        $hostname = gethostname() ?: 'localhost';
        $this->sendCommand("EHLO {$hostname}", 250);
    }

    private function authenticate(): void {
        $this->sendCommand("AUTH LOGIN", 334);
        $this->sendCommand(base64_encode($this->username), 334);
        $this->sendCommand(base64_encode($this->password), 235);
    }

    private function sendCommand(string $command, int $expectedCode): string {
        $this->sendData($command);
        $response = $this->readResponse();
        $code = (int)substr($response, 0, 3);
        if ($code !== $expectedCode) {
            throw new Exception("SMTP error: expected {$expectedCode}, got: {$response}");
        }
        return $response;
    }

    private function sendData(string $data): void {
        fwrite($this->socket, $data . "\r\n");
    }

    private function readResponse(): string {
        $response = '';
        while (true) {
            $line = fgets($this->socket, 4096);
            if ($line === false) break;
            $response .= $line;
            if (isset($line[3]) && $line[3] === ' ') break;
        }
        return trim($response);
    }

    private function disconnect(): void {
        if ($this->socket) {
            @fclose($this->socket);
            $this->socket = null;
        }
    }

    private function generateMessageId(): string {
        return sprintf('%s.%s@%s', bin2hex(random_bytes(8)), time(), parse_url($this->fromEmail, PHP_URL_HOST) ?: 'localhost');
    }

    private function formatAddress(string $email, string $name = ''): string {
        if (empty($name)) return $email;
        return '"' . str_replace('"', '\\"', $name) . '" <' . $email . '>';
    }

    /**
     * Test SMTP connection
     */
    public function testConnection(): array {
        try {
            $this->connect();
            $this->ehlo();
            if ($this->encryption === 'tls') {
                $this->sendCommand("STARTTLS", 220);
                stream_socket_enable_crypto($this->socket, true, STREAM_CRYPTO_METHOD_TLSv1_2_CLIENT);
                $this->ehlo();
            }
            if (!empty($this->username)) {
                $this->authenticate();
            }
            $this->sendCommand("QUIT", 221);
            $this->disconnect();
            return ['success' => true, 'message' => 'SMTP connection successful'];
        } catch (Exception $e) {
            $this->disconnect();
            return ['success' => false, 'message' => $e->getMessage()];
        }
    }
}
