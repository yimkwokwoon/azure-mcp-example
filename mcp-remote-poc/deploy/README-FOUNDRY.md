MCP remote server – Foundry registration prep

1) Run MCP server (streamable HTTP)

PowerShell:

$env:HOST="0.0.0.0"
$env:PORT="8080"
$env:MCP_TRANSPORT="streamable_http"
python .\mcp-poc.py

2) Reverse proxy (public IP)

Pick ONE of these:

- Nginx: deploy/nginx.conf
- Caddy: deploy/Caddyfile

Replace <PUBLIC_IP> with your public IP (or preferably a domain).

3) Foundry registration details

- MCP endpoint URL: http://165.84.140.76/ (proxy rewrites to /mcp)
- Transport: streamable HTTP (SSE)
- Required headers: Accept: application/json, text/event-stream
- MCP session header used by server: Mcp-Session-Id

Notes

- HTTPS is required for production. If you do not have a domain, you cannot get a public TLS certificate from Let’s Encrypt. Use a domain for HTTPS or terminate TLS upstream.
- Ensure firewall inbound port 80 is open on the host.
- Proxy should force Host header to 127.0.0.1:8080 to avoid MCP host validation.
- If you move to HTTPS, update the URL to https://<DOMAIN>/ (proxy rewrites to /mcp).
