# Azure REST Helper + MCP Server

## Overview

This project has two parts:

1. **`src/azure_rest.py`** — Lightweight Python helpers that call Azure Resource Manager (ARM) REST APIs directly using `requests` (no Azure SDK).
2. **`mcp-remote-poc/mcp-poc.py`** — An MCP (Model Context Protocol) server that exposes those Azure helpers as tools for AI agents (e.g., Foundry, Copilot, Claude).

Architecture:
```
Agent → MCP tool call → mcp-poc.py → azure_client.py → azure_rest_formcp.py → Azure ARM REST API → JSON response
```

---

## Project Structure

```
azure-api/
├── README.md                          # This file
├── requirements.txt                   # Root deps (requests, python-dotenv, pytest)
├── src/
│   ├── .env                           # Azure credentials for the REST module
│   ├── azure_rest.py                  # REST helpers + built-in test runner
│   └── azure_rest_formcp.py           # Copy of REST helpers used by MCP server
├── mcp-remote-poc/
│   ├── .env                           # Azure credentials for the MCP server
│   ├── mcp-poc.py                     # MCP server entrypoint
│   ├── azure_client.py                # Credentials wrapper (loads .env)
│   ├── azure_rest_formcp.py           # Copy of REST helpers (local import)
│   ├── requirements.txt               # MCP server deps (mcp, uvicorn, requests, python-dotenv)
│   ├── startup.txt                    # Quick-start command
│   └── deploy/                        # Deployment configs (Caddy, nginx, App Service)
```

---

## Azure Concepts (Quick Explanation)

To call Azure ARM APIs, you need 4 values:

| Variable | Description |
|---|---|
| `AZ_TENANT_ID` | Your Microsoft Entra (Azure AD) directory ID |
| `AZ_CLIENT_ID` | Service Principal app ID |
| `AZ_CLIENT_SECRET` | Service Principal secret |
| `AZ_SUBSCRIPTION_ID` | The Azure subscription to manage |

Flow:
1. Use Tenant/Client/Secret to get an **OAuth2 access token**
2. Call ARM endpoints at `https://management.azure.com/...` with `Authorization: Bearer <token>`

---

## How to Run on a Linux VM (Step-by-Step)

### Prerequisites

- Linux VM (Ubuntu 22.04+ recommended) with Python 3.10+
- Network access to `login.microsoftonline.com` and `management.azure.com`
- An Azure Service Principal with appropriate RBAC (at least `Reader`)

### Step 1: Clone the repo

```bash
cd ~
git clone <your-repo-url> azure-api
cd azure-api
```

### Step 2: Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r mcp-remote-poc/requirements.txt
```

### Step 3: Configure credentials

Create `.env` files with your Azure credentials:

**For the REST module** (`src/.env`):
```dotenv
AZ_TENANT_ID="00000000-0000-0000-0000-000000000000"
AZ_CLIENT_ID="00000000-0000-0000-0000-000000000000"
AZ_CLIENT_SECRET="YOUR_SECRET_VALUE"
AZ_SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000000"
```

**For the MCP server** (`mcp-remote-poc/.env`):
```dotenv
AZ_TENANT_ID="00000000-0000-0000-0000-000000000000"
AZ_CLIENT_ID="00000000-0000-0000-0000-000000000000"
AZ_CLIENT_SECRET="YOUR_SECRET_VALUE"
AZ_SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000000"

# Guardrail: keep false unless you intentionally allow deploy/delete
AZ_RUN_DEPLOY="false"

# Optional: used by deploy_vm if admin_password is omitted
AZ_TEST_PASS="YourPassword123!"
```

> **Security:** Never commit `.env` to git. Never share your client secret.

### Step 4a: Run the REST module test runner (standalone)

```bash
cd ~/azure-api
source .venv/bin/activate
python3 src/azure_rest.py
```

This will:
- Load `src/.env`
- Acquire an OAuth token
- List all VMs in your subscription
- Get instance view / power state for the first VM
- Optionally run deployment tests (if `AZ_RUN_DEPLOY=true`)

### Step 4b: Run the MCP server (interactive / foreground)

```bash
cd ~/azure-api/mcp-remote-poc
source ../.venv/bin/activate

HOST=0.0.0.0 PORT=8080 MCP_TRANSPORT=streamable_http python3 mcp-poc.py
```

Expected output:
```
demo-mcp-server - INFO - Starting MCP Server on 0.0.0.0:8080 (transport=streamable_http)...
INFO:     Uvicorn running on http://0.0.0.0:8080
```

Verify it's listening:
```bash
ss -lntp | grep 8080
```

### Step 5: Run as a background process (quick)

```bash
cd ~/azure-api/mcp-remote-poc
source ../.venv/bin/activate
nohup env HOST=0.0.0.0 PORT=8080 MCP_TRANSPORT=streamable_http python3 mcp-poc.py > /tmp/mcp.log 2>&1 &
```

Check it's running:
```bash
ps aux | grep mcp-poc | grep -v grep
```

Stop it:
```bash
kill $(pgrep -f mcp-poc.py)
```

### Step 6: Run as a systemd service (recommended for production)

Create the service file:

```bash
sudo tee /etc/systemd/system/mcp-poc.service > /dev/null << 'EOF'
[Unit]
Description=MCP Azure Ops Server (mcp-poc)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=jack
WorkingDirectory=/home/jack/azure-api/mcp-remote-poc

ExecStart=/home/jack/azure-api/.venv/bin/python3 /home/jack/azure-api/mcp-remote-poc/mcp-poc.py

Environment=HOST=0.0.0.0
Environment=PORT=8080
Environment=MCP_TRANSPORT=streamable_http
EnvironmentFile=/home/jack/azure-api/mcp-remote-poc/.env

Restart=always
RestartSec=2
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mcp-poc
```

Check status / view logs:
```bash
sudo systemctl status mcp-poc
sudo journalctl -u mcp-poc -f
```

Stop / restart:
```bash
sudo systemctl stop mcp-poc
sudo systemctl restart mcp-poc
```

### Step 7: Open firewall (if accessing remotely)

On the VM (if `ufw` is enabled):
```bash
sudo ufw allow 8080/tcp
```

On Azure (if hosted on an Azure VM):
- Add an **NSG inbound rule** allowing TCP 8080 from your agent platform's IP range.

---

## REST Helper Functions (`src/azure_rest.py`)

| Function | Description |
|---|---|
| `get_access_token(tenant_id, client_id, client_secret)` | OAuth2 client credentials → bearer token |
| `list_vms(subscription_id, token, resource_group=None)` | List VMs in subscription or resource group |
| `get_vm_instance_view(subscription_id, rg, vm_name, token)` | VM instance view (statuses + power state) |
| `get_vm_power_state(instance_view)` | Parse power state → `"running"` / `"stopped"` |
| `deploy_template(subscription_id, rg, deployment_name, token, template, parameters)` | Create/update ARM deployment |
| `build_basic_vm_template(vm_name, location, ...)` | Generate a minimal ARM template for a Ubuntu VM |
| `create_or_update_vm(subscription_id, rg, vm_name, token, nic_id, ...)` | Direct VM PUT (Compute API) |
| `create_public_ip(subscription_id, rg, name, token)` | Create a public IP address |
| `create_vnet_with_subnet(subscription_id, rg, vnet_name, subnet_name, token)` | Create VNet + subnet |
| `create_nic(subscription_id, rg, nic_name, token, subnet_id, ...)` | Create a network interface |
| `delete_deployment(subscription_id, rg, deployment_name, token)` | Delete a deployment record |
| `delete_vm(subscription_id, rg, vm_name, token, force_deletion=True)` | Delete VM with async polling |

### Usage example

```python
from src.azure_rest import get_access_token, list_vms
import os

token = get_access_token(
    os.environ["AZ_TENANT_ID"],
    os.environ["AZ_CLIENT_ID"],
    os.environ["AZ_CLIENT_SECRET"],
)

resp = list_vms(os.environ["AZ_SUBSCRIPTION_ID"], token, resource_group="my-rg")
for vm in resp.get("value", []):
    print(vm["name"], vm.get("location"))
```

---

## MCP Server Tools (`mcp-remote-poc/mcp-poc.py`)

### Read-only tools (safe)

| Tool | Arguments | Description |
|---|---|---|
| `list_vms` | `resource_group` (optional) | List VMs (single page) |
| `list_vms_all` | `resource_group` (optional) | List all VMs (handles pagination) |
| `get_vm_instance_view` | `resource_group`, `vm_name` | VM instance view JSON |
| `get_vm_power_state` | `resource_group`, `vm_name` | Power state (`running`/`stopped`) |
| `get_vm_status` | `resource_group`, `vm_name` | Summary: name, id, location, state |
| `mcp_capabilities` | *(none)* | Returns JSON describing all available tools |

### Write / destructive tools (guarded)

| Tool | Arguments | Description |
|---|---|---|
| `deploy_template` | `resource_group`, `deployment_name`, `template_json`, `parameters_json` | ARM template deployment (requires `AZ_RUN_DEPLOY=true`) |
| `deploy_vm` | `resource_group`, `vm_name`, `location`, `vm_size`, ... | Create VM + NIC (+ optional public IP) |
| `delete_vm_tool` | `resource_group`, `vm_name`, `force` | Delete a VM resource |
| `delete_deployment` | `resource_group`, `deployment_name` | Delete a deployment record |

### Demo / test tools

| Tool | Description |
|---|---|
| `add(a, b)` | Add two numbers (demo) |
| `get_secret_word()` | Returns a random word (demo) |
| `get_current_weather(city)` | Returns fake weather (demo) |

> **Important:** Your agent system prompt should require explicit user confirmation before calling deploy/delete tools.

---

## Troubleshooting

### "Missing Azure credentials"
- `.env` file missing or not in the right location
- If running via systemd, check `EnvironmentFile=` path is correct
- Check logs: `sudo journalctl -u mcp-poc -n 200 --no-pager`

### 401 Unauthorized
- Wrong tenant/client/secret
- Client secret expired or copied with extra whitespace
- Fix: recreate the secret and update `.env`

### 403 AuthorizationFailed
- Service Principal RBAC not assigned (or wrong scope)
- Fix: assign at least `Reader` role at the correct subscription/resource group

### Empty VM list
- Wrong subscription ID or resource group name
- No VMs exist in the queried scope

### Server works locally but not remotely
- Bound to `127.0.0.1` instead of `0.0.0.0` → set `HOST=0.0.0.0`
- Linux firewall (`ufw`) or Azure NSG blocking port 8080

---

## Security Recommendations

- Use **least privilege RBAC** (`Reader` for read-only; `Contributor` scoped to a lab RG only)
- Keep `AZ_RUN_DEPLOY=false` by default; enable only when needed
- Never commit `.env` or log secrets/tokens
- Restrict inbound access to the MCP port (trusted IPs only)
- Prefer **Managed Identity** if running on Azure (avoids secrets entirely)

---

## Extending: Add a New Azure API as an MCP Tool

1. Add a REST helper in `azure_rest_formcp.py` (and copy to `mcp-remote-poc/azure_rest_formcp.py`):
   ```python
   def my_new_api(subscription_id, token, ...) -> dict:
       url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/..."
       r = requests.get(url, headers=_headers(token))
       r.raise_for_status()
       return r.json()
   ```

2. Add an MCP tool wrapper in `mcp-poc.py`:
   ```python
   @mcp.tool()
   def my_new_tool(resource_group: str) -> str:
       client = _get_client()
       token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
       result = azure_rest.my_new_api(client.subscription_id, token, resource_group)
       return json.dumps(result)
   ```

3. Update your agent system prompt to document the new tool's parameters and guardrails.
