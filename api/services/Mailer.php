<?php
/**
 * Pure PHP SMTP mailer (no dependencies)
 */
class Mailer {
    private string $host, $encryption, $username, $password, $fromEmail, $fromName;
    private int $port;
    private $socket = null;

    public function __construct() {
        $s = Router::getSettings(['smtp_host','smtp_port','smtp_encryption','smtp_username','smtp_password','from_email','from_name']);
        $this->host = $s['smtp_host'] ?? 'localhost';
        $this->port = (int)($s['smtp_port'] ?? 25);
        $this->encryption = $s['smtp_encryption'] ?? '';
        $this->username = $s['smtp_username'] ?? '';
        $this->password = $s['smtp_password'] ?? '';
        $this->fromEmail = $s['from_email'] ?? 'noreply@example.com';
        $this->fromName = $s['from_name'] ?? APP_NAME;
    }

    public function send(string $to, string $subject, string $html, string $text = '', array $extra = []): array {
        $msgId = bin2hex(random_bytes(8)) . '.' . time() . '@nexus';
        $boundary = 'b_' . md5(uniqid());

        $headers = "From: \"{$this->fromName}\" <{$this->fromEmail}>\r\n";
        $headers .= "To: {$to}\r\nSubject: {$subject}\r\n";
        $headers .= "Message-ID: <{$msgId}>\r\nMIME-Version: 1.0\r\n";
        $headers .= "Content-Type: multipart/alternative; boundary=\"{$boundary}\"\r\n";
        $headers .= "Date: " . date('r') . "\r\nX-Mailer: " . APP_NAME . "\r\n";
        if (!empty($extra['reply_to'])) $headers .= "Reply-To: {$extra['reply_to']}\r\n";
        if (!empty($extra['list_unsubscribe'])) {
            $headers .= "List-Unsubscribe: <{$extra['list_unsubscribe']}>\r\n";
        }

        $body = "--{$boundary}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n";
        $body .= ($text ?: strip_tags($html)) . "\r\n";
        $body .= "--{$boundary}\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n";
        $body .= $html . "\r\n--{$boundary}--\r\n";

        try {
            $this->connect();
            $this->ehlo();
            if ($this->encryption === 'tls') {
                $this->cmd("STARTTLS", 220);
                stream_socket_enable_crypto($this->socket, true, STREAM_CRYPTO_METHOD_TLSv1_2_CLIENT);
                $this->ehlo();
            }
            if ($this->username) $this->auth();
            $this->cmd("MAIL FROM:<{$this->fromEmail}>", 250);
            $this->cmd("RCPT TO:<{$to}>", 250);
            $this->cmd("DATA", 354);
            fwrite($this->socket, $headers . "\r\n" . $body . "\r\n.\r\n");
            $this->read();
            $this->cmd("QUIT", 221);
            $this->disconnect();
            return ['success' => true, 'message_id' => $msgId];
        } catch (\Exception $e) {
            $this->disconnect();
            return ['success' => false, 'error' => $e->getMessage(), 'message_id' => $msgId];
        }
    }

    public function testConnection(): array {
        try {
            $this->connect(); $this->ehlo();
            if ($this->encryption === 'tls') {
                $this->cmd("STARTTLS", 220);
                stream_socket_enable_crypto($this->socket, true, STREAM_CRYPTO_METHOD_TLSv1_2_CLIENT);
                $this->ehlo();
            }
            if ($this->username) $this->auth();
            $this->cmd("QUIT", 221); $this->disconnect();
            return ['success' => true, 'message' => 'SMTP connection OK'];
        } catch (\Exception $e) {
            $this->disconnect();
            return ['success' => false, 'message' => $e->getMessage()];
        }
    }

    private function connect(): void {
        $host = ($this->encryption === 'ssl' ? 'ssl://' : '') . $this->host;
        $this->socket = @stream_socket_client("{$host}:{$this->port}", $en, $es, 30);
        if (!$this->socket) throw new \Exception("SMTP connect failed: {$es}");
        stream_set_timeout($this->socket, 30);
        $this->read();
    }

    private function ehlo(): void { $this->cmd("EHLO " . (gethostname() ?: 'localhost'), 250); }
    private function auth(): void {
        $this->cmd("AUTH LOGIN", 334);
        $this->cmd(base64_encode($this->username), 334);
        $this->cmd(base64_encode($this->password), 235);
    }

    private function cmd(string $c, int $expect): string {
        fwrite($this->socket, $c . "\r\n");
        $r = $this->read();
        if ((int)substr($r, 0, 3) !== $expect) throw new \Exception("SMTP: expected {$expect}, got: {$r}");
        return $r;
    }

    private function read(): string {
        $r = '';
        while (true) {
            $l = fgets($this->socket, 4096);
            if ($l === false) break;
            $r .= $l;
            if (isset($l[3]) && $l[3] === ' ') break;
        }
        return trim($r);
    }

    private function disconnect(): void { if ($this->socket) { @fclose($this->socket); $this->socket = null; } }
}
