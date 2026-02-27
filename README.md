# Azure REST Helper + MCP Server

## Overview

This is an MCP (Model Context Protocol) server that exposes Azure VM management operations as tools for AI agents (e.g., Azure AI Foundry agents, Copilot, Claude Desktop).

It calls **Azure Resource Manager (ARM) REST APIs** directly using `requests` (no Azure SDK), so you can see exactly what's being sent to Azure.

Architecture:
```
End-user → Foundry Agent → MCP tool call → mcp-poc.py → azure_rest_formcp.py → Azure ARM REST API
```

The MCP server runs on a **Linux VM** and exposes a streamable HTTP endpoint that Foundry agents connect to remotely.

---

## Project Structure

```
azure-api/
├── README.md                          # This file
├── requirements.txt                   # Root deps (requests, python-dotenv, pytest)
├── .gitignore                         # Excludes .venv, .env, __pycache__, etc.
├── mcp-remote-poc/
│   ├── .env                           # Azure credentials (DO NOT COMMIT)
│   ├── mcp-poc.py                     # MCP server entrypoint (22 tools)
│   ├── azure_client.py                # Credentials wrapper (loads .env)
│   ├── azure_rest_formcp.py           # Azure ARM REST helper functions
│   ├── requirements.txt               # MCP server deps (mcp, uvicorn, requests, python-dotenv)
│   ├── startup.txt                    # Quick-start command
│   └── deploy/                        # Deployment configs (Caddy, nginx, App Service)
```

---

## Azure API Versions

| Resource Type | API Version |
|---|---|
| Microsoft.Compute (VMs, VM Sizes, Images) | `2024-11-01` |
| Microsoft.Network (IP, VNet, NIC) | `2024-05-01` |
| Microsoft.Resources (Deployments, Locations) | `2024-07-01` |
| Default VM Image | Ubuntu 24.04 LTS (`Canonical / ubuntu-24_04-lts / server`) |

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
- An Azure Service Principal with appropriate RBAC (at least `Reader`; `Contributor` for deploy/delete)

### Step 1: Clone the repo

```bash
cd ~
git clone https://github.com/yimkwokwoon/azure-mcp-example.git azure-api
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

Create `mcp-remote-poc/.env` with your Azure credentials:

```dotenv
AZ_TENANT_ID="00000000-0000-0000-0000-000000000000"
AZ_CLIENT_ID="00000000-0000-0000-0000-000000000000"
AZ_CLIENT_SECRET="YOUR_SECRET_VALUE"
AZ_SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000000"

# Optional: used by deploy_vm if admin_password is omitted
AZ_TEST_PASS="YourPassword123!"
```

> **Security:** Never commit `.env` to git. Never share your client secret.

### Step 4: Run the MCP server (foreground)

```bash
cd ~/azure-api/mcp-remote-poc
source ../.venv/bin/activate

HOST=0.0.0.0 PORT=8080 MCP_TRANSPORT=streamable_http python3 mcp-poc.py
```

Expected output:
```
demo-mcp-server - INFO - Starting MCP Server on 0.0.0.0:8080 (transport=streamable_http)...
demo-mcp-server - INFO - Serving streamable HTTP endpoint at /mcp
INFO:     Uvicorn running on http://0.0.0.0:8080
```

### Step 5: Run as a systemd service (recommended for production)

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

sudo systemctl daemon-reload
sudo systemctl enable --now mcp-poc
```

Check status / logs / restart:
```bash
sudo systemctl status mcp-poc
sudo journalctl -u mcp-poc -f
sudo systemctl restart mcp-poc
```

### Step 6: Open firewall (if accessing remotely)

```bash
# On the VM (if ufw is enabled)
sudo ufw allow 8080/tcp

# On Azure: add an NSG inbound rule allowing TCP 8080
```

---

## Connecting to Azure AI Foundry Agent

### MCP Registration Details

| Setting | Value |
|---|---|
| MCP Endpoint URL | `http://<YOUR_VM_PUBLIC_IP>:8080/mcp` |
| Transport | Streamable HTTP |
| Required Headers | `Accept: application/json, text/event-stream` |

If using a reverse proxy (nginx/Caddy) on port 80:
- URL becomes `http://<YOUR_VM_PUBLIC_IP>/` (proxy rewrites to `/mcp`)
- See `deploy/nginx.conf` or `deploy/Caddyfile` for config

### Recommended System Prompt for Foundry Agent

Copy and paste this as your Foundry agent's system prompt:

```
## Character
Act as a cautious Azure operator: readable, precise, and risk-aware.
Ask clarifying questions when intent or parameters are ambiguous.
Never assume destructive intent; always confirm.

## Skills (tools you may call)

### Read-only / discovery tools (safe, no confirmation needed)
- mcp_capabilities — describe available tools (no params).
- list_vms(resource_group=optional) — list VMs (single page). If resource_group omitted, ask user whether to list across the whole subscription.
- list_vms_all(resource_group=optional) — aggregate all pages. Confirm full-subscription scans.
- get_vm_instance_view(resource_group, vm_name) — inspect VM statuses (requires both).
- get_vm_power_state(resource_group, vm_name) — return parsed power state (requires both).
- get_vm_status(resource_group, vm_name) — small summary (requires both).
- list_locations(filter=optional, top=30) — list available Azure regions. Use filter to narrow by keyword, e.g. filter="asia".
- list_vm_sizes(location, filter=optional, min_vcpus=optional, max_vcpus=optional, min_memory_gb=optional, max_memory_gb=optional, top=20) — list VM sizes with filtering. Always use filters to keep results small.
- list_vm_image_publishers(location, search=optional, top=20) — returns curated common publishers by default. Use search to find niche publishers.
- list_vm_image_offers(location, publisher, search=optional, top=25) — list image product lines for a publisher.
- list_vm_image_skus(location, publisher, offer, search=optional, top=25) — list specific SKUs for an offer.
- list_disk_types() — list the 7 Azure managed disk types with cost/performance descriptions.

### Write / deploy tools (require explicit confirmation)
- deploy_template(resource_group, deployment_name, template_json, parameters_json="{}") — guarded deploy.
- deploy_vm(resource_group, vm_name, location, vm_size, admin_username, admin_password, nic_id, vnet_name, subnet_name, no_public_ip, image_publisher, image_offer, image_sku, image_version, os_disk_type, os_disk_size_gb, os_type) — guarded VM create with full customization.
- delete_deployment(resource_group, deployment_name) — delete a deployment record (does NOT delete resources).
- delete_vm_tool(resource_group, vm_name, force=True) — guarded VM delete.

## VM deployment workflow (IMPORTANT)

When a user asks to create/deploy a VM, NEVER jump straight to calling deploy_vm.
Follow this interactive workflow to collect preferences:

### Step 1 — Clarify intent & gather requirements
Ask the user:
- What is the VM for? (dev/test, production, GPU workload, etc.)
- Any OS preference? (Linux / Windows)
- Any region preference?
- Any budget or size constraints?

### Step 2 — Present available options using discovery tools
Based on user answers, call discovery tools and present concise options:

1. **Region** — If user hasn't specified, call list_locations(filter="keyword") and suggest common ones.
2. **VM Size** — Call list_vm_sizes(location, min_vcpus=X, max_vcpus=Y) and present a short table of 3-5 matches.
3. **OS Image** — Call list_vm_image_publishers → list_vm_image_offers → list_vm_image_skus to drill down.
4. **Disk** — Call list_disk_types() and recommend based on workload (dev=StandardSSD_LRS, prod=Premium_LRS).
5. **Networking** — Ask: "Do you need a public IP?" Default is no (safer).

### Step 3 — Summarize and confirm
Present a complete summary of ALL parameters before deploying:

    I will create a VM with these settings:
      Resource Group : rg-dev
      VM Name        : my-vm-01
      Region         : eastasia
      VM Size        : Standard_D2as_v5 (2 vCPUs, 8 GB RAM)
      OS Image       : Canonical / ubuntu-24_04-lts / server (latest)
      OS Disk        : Premium_LRS, default size
      Public IP      : No
      VNet / Subnet  : vnet-jack / default
      Admin User     : jack
      Password       : (from environment)

    This will create billable resources.

Then require an explicit confirmation phrase:
"CONFIRM: deploy_vm vm_name=my-vm-01 in rg-dev — I approve creating billable resources."

### Step 4 — Deploy
Only after receiving explicit confirmation, call deploy_vm with all collected parameters.
Report the result clearly, including provisioning state and any resource IDs.

## Limitations & guardrails
- For writes/deletes/deploys, require an explicit user confirmation phrase that repeats the exact parameters and acknowledges billable/destructive effects.
- Never return secrets (client secret, access token) in responses or logs.
- If a tool returns an HTTP/auth error, show the error diagnostics and suggest credential/network fixes rather than retry silently.
- When listing VM sizes or images, always use filters to keep results small. Offer to show more if user asks.

## Parameter collection protocol
- Always list required parameters and any sensible defaults.
- For passwords or secrets: prefer AZ_TEST_PASS or ask user to provide a value; never store or echo secrets.
- For discovery tools (list_*), call them proactively when the user is exploring options. Do NOT require confirmation for read-only tools.

## Security & privacy
- Never echo or expose AZ_CLIENT_SECRET, tokens, or other secrets.
- Pre-deploy check: validate credentials and show existing resources before deploying.
- Deletion confirmation: require explicit confirmation with resource identity.

## Behavioral constraints
- Keep responses short and actionable.
- Default to safer/read-only choices.
- If uncertain, ask instead of acting.
- When presenting options from discovery tools, use markdown tables for readability.
- Proactively suggest cost-efficient defaults for dev/test workloads.
```

---

## MCP Server Tools Reference (22 tools)

### Discovery tools (read-only, safe)

| Tool | Arguments | Description |
|---|---|---|
| `mcp_capabilities` | *(none)* | Returns JSON describing all available tools |
| `list_locations` | `filter` (optional), `top` (default 30) | List Azure regions. Use `filter="asia"` to narrow. |
| `list_vm_sizes` | `location`, `filter`, `min_vcpus`, `max_vcpus`, `min_memory_gb`, `max_memory_gb`, `top` (default 20) | List VM sizes with filtering. Returns name, vCPUs, memoryGB, maxDataDisks. |
| `list_vm_image_publishers` | `location`, `search` (optional), `top` (default 20) | Returns curated common publishers by default. Use `search` to query the full Azure catalog. |
| `list_vm_image_offers` | `location`, `publisher`, `search` (optional), `top` (default 25) | List image offers (e.g. ubuntu-24_04-lts, WindowsServer). |
| `list_vm_image_skus` | `location`, `publisher`, `offer`, `search` (optional), `top` (default 25) | List image SKUs (e.g. server, 2022-datacenter-g2). |
| `list_disk_types` | *(none)* | Returns 7 Azure managed disk types with performance descriptions. |

### VM inspection tools (read-only, safe)

| Tool | Arguments | Description |
|---|---|---|
| `list_vms` | `resource_group` (optional) | List VMs (single page) |
| `list_vms_all` | `resource_group` (optional) | List all VMs (handles pagination) |
| `get_vm_instance_view` | `resource_group`, `vm_name` | VM instance view JSON |
| `get_vm_power_state` | `resource_group`, `vm_name` | Power state (`running`/`stopped`) |
| `get_vm_status` | `resource_group`, `vm_name` | Summary: name, id, location, state |

### Write / destructive tools (require confirmation)

| Tool | Key Arguments | Description |
|---|---|---|
| `deploy_vm` | `resource_group`, `vm_name`, `location`, `vm_size`, `image_publisher`, `image_offer`, `image_sku`, `image_version`, `os_disk_type`, `os_disk_size_gb`, `os_type`, `no_public_ip`, ... | Create VM with full customization |
| `deploy_template` | `resource_group`, `deployment_name`, `template_json`, `parameters_json` | ARM template deployment |
| `delete_vm_tool` | `resource_group`, `vm_name`, `force` | Delete a VM resource |
| `delete_deployment` | `resource_group`, `deployment_name` | Delete a deployment record |

### `deploy_vm` — Full Parameter Reference

| Parameter | Type | Default | Description |
|---|---|---|---|
| `resource_group` | str | *(required)* | Azure resource group name |
| `vm_name` | str | *(required)* | VM name |
| `location` | str | `eastasia` | Azure region (use `list_locations` to discover) |
| `vm_size` | str | `Standard_D2as_v5` | VM SKU (use `list_vm_sizes` to discover) |
| `admin_username` | str | `jack` | SSH/RDP admin username |
| `admin_password` | str | `None` | Admin password (falls back to `AZ_TEST_PASS` env var) |
| `nic_id` | str | `None` | Existing NIC resource ID. If omitted, NIC is auto-created. |
| `vnet_name` | str | `vnet-jack` | VNet to attach NIC to (when auto-creating) |
| `subnet_name` | str | `default` | Subnet within the VNet |
| `no_public_ip` | bool | `True` | If `False`, a public IP is created and attached |
| `image_publisher` | str | `Canonical` | OS publisher (use `list_vm_image_publishers`) |
| `image_offer` | str | `ubuntu-24_04-lts` | Image offer (use `list_vm_image_offers`) |
| `image_sku` | str | `server` | Image SKU (use `list_vm_image_skus`) |
| `image_version` | str | `latest` | Image version |
| `os_disk_type` | str | `Premium_LRS` | Disk SKU (use `list_disk_types`) |
| `os_disk_size_gb` | int | `None` | Disk size in GB. None = Azure default. |
| `os_type` | str | `linux` | `linux` or `windows` — controls OS config |

### Demo tools

| Tool | Description |
|---|---|
| `add(a, b)` | Add two numbers (demo) |
| `get_secret_word()` | Returns a random word (demo) |
| `get_current_weather(city)` | Returns fake weather (demo) |

---

## Test Prompts for Your Foundry Agent

After connecting the MCP server, try these prompts in your Foundry agent:

### 1. Basic connectivity test
```
Call the add tool with 3 and 5.
```
Expected: Returns `8`.

### 2. List VMs
```
List all VMs in resource group "poc".
```
Expected: Returns VM names, locations, and states.

### 3. Check VM status
```
What is the power state of VM "vm-mcp-server" in resource group "poc"?
```
Expected: Returns `running` or `deallocated`.

### 4. Explore available regions
```
Show me Azure regions in Asia.
```
Expected: Agent calls `list_locations(filter="asia")` and shows ~5 regions.

### 5. Explore VM sizes
```
What VM sizes are available in eastasia with 2-4 vCPUs?
```
Expected: Agent calls `list_vm_sizes(location="eastasia", min_vcpus=2, max_vcpus=4)` and shows a filtered table.

### 6. Explore OS images
```
What Ubuntu images are available in eastasia?
```
Expected: Agent calls `list_vm_image_offers(location="eastasia", publisher="Canonical")` then drills into SKUs.

### 7. List disk types
```
What disk types can I choose from?
```
Expected: Agent calls `list_disk_types()` and shows the 7 options with descriptions.

### 8. Full VM deployment workflow
```
I want to create a cheap Ubuntu dev/test VM in East Asia with no public IP.
```
Expected: Agent walks through the 4-step workflow:
1. Asks clarifying questions
2. Calls discovery tools to find options
3. Presents a summary table and asks for confirmation
4. Only deploys after explicit confirmation

### 9. Windows VM deployment
```
Create a Windows Server VM in westus with 4 vCPUs for a production workload.
```
Expected: Agent discovers Windows images, suggests Premium_LRS disk, asks for confirmation.

### 10. Delete a VM
```
Delete VM "test-vm-01" in resource group "rg-dev".
```
Expected: Agent asks for explicit confirmation before calling `delete_vm_tool`.

---

## REST Helper Functions (`azure_rest_formcp.py`)

| Function | Description |
|---|---|
| `get_access_token(tenant_id, client_id, client_secret)` | OAuth2 client credentials → bearer token |
| `list_vms(subscription_id, token, resource_group=None)` | List VMs in subscription or resource group |
| `get_vm_instance_view(subscription_id, rg, vm_name, token)` | VM instance view (statuses + power state) |
| `get_vm_power_state(instance_view)` | Parse power state → `"running"` / `"stopped"` |
| `list_locations(subscription_id, token)` | List Azure regions |
| `list_vm_sizes(subscription_id, location, token)` | List VM sizes in a region |
| `list_vm_image_publishers(subscription_id, location, token)` | List image publishers |
| `list_vm_image_offers(subscription_id, location, publisher, token)` | List image offers |
| `list_vm_image_skus(subscription_id, location, publisher, offer, token)` | List image SKUs |
| `deploy_template(subscription_id, rg, deployment_name, token, template, params)` | Create/update ARM deployment |
| `build_basic_vm_template(vm_name, location, ...)` | Generate a minimal ARM template for a VM |
| `create_or_update_vm(subscription_id, rg, vm_name, token, nic_id, ...)` | Direct VM PUT (accepts os_disk_type, os_disk_size_gb, os_type) |
| `create_public_ip(subscription_id, rg, name, token)` | Create a public IP address |
| `create_vnet_with_subnet(subscription_id, rg, vnet_name, subnet_name, token)` | Create VNet + subnet |
| `create_nic(subscription_id, rg, nic_name, token, subnet_id, ...)` | Create a network interface |
| `delete_deployment(subscription_id, rg, deployment_name, token)` | Delete a deployment record |
| `delete_vm(subscription_id, rg, vm_name, token, force_deletion=True)` | Delete VM with async polling |

---

## Troubleshooting

### "Missing Azure credentials"
- `.env` file missing or not in the right location
- If running via systemd, check `EnvironmentFile=` path
- Check logs: `sudo journalctl -u mcp-poc -n 200 --no-pager`

### 401 Unauthorized
- Wrong tenant/client/secret or secret expired
- Fix: recreate the secret and update `.env`

### 403 AuthorizationFailed
- Service Principal RBAC not assigned at the correct scope
- Fix: assign `Reader` (read-only) or `Contributor` (deploy/delete) role

### Port already in use
```bash
kill $(pgrep -f mcp-poc.py)
# or
sudo systemctl stop mcp-poc
```

### Context window overflow in Foundry agent
- The discovery tools use server-side filtering and return limited results by default
- Always use `filter`/`search` parameters to narrow results
- Use `top` parameter to limit result count
- If still too large, reduce `top` to 5-10

### Server works locally but not remotely
- Bound to `127.0.0.1` instead of `0.0.0.0` → set `HOST=0.0.0.0`
- Linux firewall (`ufw`) or Azure NSG blocking port 8080

---

## Security Recommendations

- Use **least privilege RBAC** (`Reader` for read-only; `Contributor` scoped to a lab RG only)
- Never commit `.env` or log secrets/tokens
- Restrict inbound access to the MCP port (trusted IPs only)
- Prefer **Managed Identity** if running on Azure (avoids secrets entirely)
- Agent system prompt should **require explicit confirmation** before write/delete operations

---

## Repository

GitHub: https://github.com/yimkwokwoon/azure-mcp-example
