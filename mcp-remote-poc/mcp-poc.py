# pip install fastmcp requests

import logging
import os
import random
import sys
from pathlib import Path
import json

# Ensure project root is importable so we can load `src.azure_client` and `src.azure_rest`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import sys as _sys
print(f"DEBUG: ROOT={ROOT}", file=_sys.stderr)
print("DEBUG: sys.path (first 5):", file=_sys.stderr)
for p in _sys.path[:5]:
    print(p, file=_sys.stderr)

# Load .env from several locations so Azure credentials are available to imported modules
try:
    from dotenv import load_dotenv
    # 1) mcp-remote-poc/.env (next to this script)
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    # 2) project root .env
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except Exception:
    pass

from mcp.server.fastmcp import FastMCP

try:
    # Prefer local copies placed in the mcp-remote-poc folder
    from azure_client import AzureClient
    import azure_rest_formcp as azure_rest
except Exception:
    import traceback, sys
    print("Failed importing local azure modules (azure_client / azure_rest_formcp):", file=sys.stderr)
    traceback.print_exc()
    AzureClient = None
    azure_rest = None

# FORCE ENABLE DEPLOYMENTS (hardcoded). To revert, remove or set AZ_RUN_DEPLOY to 'false' in environment.
os.environ["AZ_RUN_DEPLOY"] = os.environ.get("AZ_RUN_DEPLOY", "true")
name = "demo-mcp-server"
logger = logging.getLogger(name)
logger.info("AZ_RUN_DEPLOY hardcoded to: %s", os.environ.get("AZ_RUN_DEPLOY"))


class HostRewriteMiddleware:
    def __init__(self, app, host="127.0.0.1:8080"):
        self.app = app
        self.host = host.encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope.get("type") in ("http", "websocket"):
            headers = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"host"]
            headers.append((b"host", self.host))
            scope = dict(scope)
            scope["headers"] = headers
        await self.app(scope, receive, send)

name = "demo-mcp-server"
logging.basicConfig(
    level=logging.INFO,
    format='%(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(name)


host = os.environ.get('HOST', '0.0.0.0')
port = int(os.environ.get('PORT', 8080))
transport = os.environ.get('MCP_TRANSPORT', 'sse')
# `FastMCP` may not accept a `logger=` keyword. Create the server
# without the arg and attach the logger afterwards if the object
# exposes a compatible attribute.
mcp = FastMCP(name, port=port)
if hasattr(mcp, 'logger'):
    mcp.logger = logger
elif hasattr(mcp, '_logger'):
    mcp._logger = logger

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    logger.info(f"Tool called: add({a}, {b})")
    return a + b

@mcp.tool()
def get_secret_word() -> str:
    """Get a random secret word"""
    logger.info("Tool called: get_secret_word()")
    return random.choice(["apple", "banana", "cherry"])


@mcp.tool()
def get_current_weather(city: str) -> str:
    """Get current weather for a city"""
    logger.info(f"Tool called: get_current_weather({city})")
    return "15 Degrees Celsius, Sunny in " + city


@mcp.tool()
def mcp_capabilities() -> str:
    """Return a JSON string describing the MCP tools exposed by this server.

    Agents can call this first to learn what tools are available and how to use them.
    """
    caps = {
        "description": "MCP tools exposing Azure VM management and discovery helpers",
        "tools": {
            "list_vms": "List VMs in a subscription or resource group. Args: resource_group (optional)",
            "list_vms_all": "List all VMs (handles pagination). Args: resource_group (optional)",
            "get_vm_instance_view": "Return VM instanceView JSON. Args: resource_group, vm_name",
            "get_vm_power_state": "Return parsed VM power state (running/stopped). Args: resource_group, vm_name",
            "get_vm_status": "Convenience: returns name, id, location, provisioningState, powerState. Args: resource_group, vm_name",
            "list_locations": "List Azure regions. Args: filter (optional substring), top (default 30).",
            "list_vm_sizes": "List VM sizes in a region with filtering. Args: location, filter, min_vcpus, max_vcpus, min_memory_gb, max_memory_gb, top (default 20).",
            "list_vm_image_publishers": "List OS image publishers. Returns curated common list by default. Args: location, search (optional), top.",
            "list_vm_image_offers": "List image offers for a publisher. Args: location, publisher, search (optional), top.",
            "list_vm_image_skus": "List image SKUs. Args: location, publisher, offer, search (optional), top.",
            "list_disk_types": "List Azure managed disk types with descriptions. No args.",
            "deploy_template": "(Guarded) Deploy an ARM template. Args: resource_group, deployment_name, template_json, parameters_json. Requires AZ_RUN_DEPLOY=true",
            "deploy_vm": "(Guarded) Create a VM with full customization. See tool docstring for all parameters.",
            "delete_deployment": "Delete a deployment record. Args: resource_group, deployment_name",
            "delete_vm_tool": "(Guarded) Delete a VM resource. Args: resource_group, vm_name, force"
        }
    }
    return json.dumps(caps)


def _get_client():
    if AzureClient is None:
        raise RuntimeError("AzureClient not importable — ensure project root is on PYTHONPATH and `src` package exists")
    return AzureClient.from_env()


@mcp.tool()
def list_vms(resource_group: str = None) -> str:
    """List VMs (single page) using azure_rest.list_vms. Returns JSON string.

    resource_group: optional resource group name (string). If omitted lists across subscription.
    """
    logger.info(f"Tool called: list_vms(resource_group={resource_group})")
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
    resp = azure_rest.list_vms(client.subscription_id, token, resource_group)
    return json.dumps(resp)


@mcp.tool()
def list_vms_all(resource_group: str = None) -> str:
    """List all VMs (pages aggregated). Returns JSON string array of VM objects."""
    logger.info(f"Tool called: list_vms_all(resource_group={resource_group})")
    client = _get_client()
    vms = client.list_vms_all(resource_group)
    return json.dumps(vms)


@mcp.tool()
def get_vm_instance_view(resource_group: str, vm_name: str) -> str:
    """Return the VM instanceView JSON (as string)."""
    logger.info(f"Tool called: get_vm_instance_view({resource_group}, {vm_name})")
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
    iv = azure_rest.get_vm_instance_view(client.subscription_id, resource_group, vm_name, token)
    return json.dumps(iv)


@mcp.tool()
def get_vm_power_state(resource_group: str, vm_name: str) -> str:
    """Return parsed power state string for a VM (e.g., 'running', 'stopped')."""
    logger.info(f"Tool called: get_vm_power_state({resource_group}, {vm_name})")
    client = _get_client()
    s = client.get_vm_power_state_safe(resource_group, vm_name)
    return json.dumps({"powerState": s})


@mcp.tool()
def get_vm_status(resource_group: str, vm_name: str) -> str:
    """Convenience call: returns a small summary of VM (name, id, location, provisioningState, powerState)."""
    logger.info(f"Tool called: get_vm_status({resource_group}, {vm_name})")
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
    # fetch top-level VM resource
    vms = azure_rest.list_vms(client.subscription_id, token, resource_group)
    # find by name
    for vm in vms.get("value", []):
        if vm.get("name") == vm_name:
            iv = azure_rest.get_vm_instance_view(client.subscription_id, resource_group, vm_name, token)
            power = azure_rest.get_vm_power_state(iv)
            summary = {
                "name": vm.get("name"),
                "id": vm.get("id"),
                "location": vm.get("location"),
                "provisioningState": vm.get("properties", {}).get("provisioningState"),
                "powerState": power,
            }
            return json.dumps(summary)
    return json.dumps({"error": "VM not found in resource group (or resource_group omitted)"})


# ---------------------------------------------------------------------------
# Discovery tools (read-only — no confirmation needed)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_locations(filter: str = None, top: int = 30) -> str:
    """List available Azure regions for the subscription.

    Args:
        filter: Optional text to filter region names (case-insensitive substring match).
                E.g. 'asia', 'us', 'europe'.
        top: Max results to return (default 30).

    Returns JSON with matched regions and total count.
    """
    logger.info(f"Tool called: list_locations(filter={filter}, top={top})")
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
    locations = azure_rest.list_locations(client.subscription_id, token)
    # Simplify to just name and displayName
    simplified = [{"name": loc.get("name"), "displayName": loc.get("displayName")} for loc in locations]
    # Apply filter
    if filter:
        f = filter.lower()
        simplified = [l for l in simplified if f in (l.get("name") or "").lower() or f in (l.get("displayName") or "").lower()]
    total = len(simplified)
    return json.dumps({"total": total, "showing": min(top, total), "locations": simplified[:top]})


@mcp.tool()
def list_vm_sizes(location: str, filter: str = None, min_vcpus: int = None, max_vcpus: int = None, min_memory_gb: float = None, max_memory_gb: float = None, top: int = 20) -> str:
    """List available VM sizes in a region with filtering.

    Args:
        location: Azure region name, e.g. 'eastasia', 'eastus'.
        filter: Substring match on VM size name (case-insensitive). E.g. 'Standard_D', 'Standard_B'.
        min_vcpus: Minimum vCPU count.
        max_vcpus: Maximum vCPU count.
        min_memory_gb: Minimum memory in GB.
        max_memory_gb: Maximum memory in GB.
        top: Max results to return (default 20).

    Returns JSON with matched sizes (name, vCPUs, memoryGB, maxDataDisks) and total count.
    """
    logger.info(f"Tool called: list_vm_sizes({location}, filter={filter}, vcpus={min_vcpus}-{max_vcpus}, mem={min_memory_gb}-{max_memory_gb}, top={top})")
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
    raw = azure_rest.list_vm_sizes(client.subscription_id, location, token)
    # Trim to essential fields and convert memory from MB to GB
    sizes = []
    for s in raw:
        name = s.get("name", "")
        vcpus = s.get("numberOfCores", 0)
        mem_mb = s.get("memoryInMB", 0)
        mem_gb = round(mem_mb / 1024, 1)
        max_disks = s.get("maxDataDiskCount", 0)
        # Apply filters
        if filter and filter.lower() not in name.lower():
            continue
        if min_vcpus is not None and vcpus < min_vcpus:
            continue
        if max_vcpus is not None and vcpus > max_vcpus:
            continue
        if min_memory_gb is not None and mem_gb < min_memory_gb:
            continue
        if max_memory_gb is not None and mem_gb > max_memory_gb:
            continue
        sizes.append({"name": name, "vCPUs": vcpus, "memoryGB": mem_gb, "maxDataDisks": max_disks})
    total = len(sizes)
    return json.dumps({"total": total, "showing": min(top, total), "sizes": sizes[:top]})


# Well-known publishers so the agent doesn't need to fetch the full 500+ list
_COMMON_PUBLISHERS = [
    {"name": "Canonical", "description": "Ubuntu Linux"},
    {"name": "MicrosoftWindowsServer", "description": "Windows Server"},
    {"name": "MicrosoftWindowsDesktop", "description": "Windows 10/11 Desktop"},
    {"name": "RedHat", "description": "Red Hat Enterprise Linux (RHEL)"},
    {"name": "SUSE", "description": "SUSE Linux Enterprise"},
    {"name": "Debian", "description": "Debian Linux"},
    {"name": "Oracle", "description": "Oracle Linux"},
    {"name": "OpenLogic", "description": "CentOS-based Linux"},
    {"name": "MicrosoftSQLServer", "description": "SQL Server on Windows/Linux"},
    {"name": "kinvolk", "description": "Flatcar Container Linux"},
]


@mcp.tool()
def list_vm_image_publishers(location: str, search: str = None, top: int = 20) -> str:
    """List VM image publishers available in a region.

    By default returns a curated list of common publishers (Ubuntu, Windows, RHEL, etc.).
    Use `search` to find a specific publisher by name substring.

    Args:
        location: Azure region name, e.g. 'eastasia'.
        search: Optional substring to search publisher names (case-insensitive).
                If omitted, returns curated common publishers only.
        top: Max results to return (default 20).

    Returns JSON with matched publishers and total count.
    """
    logger.info(f"Tool called: list_vm_image_publishers({location}, search={search}, top={top})")
    if not search:
        # Return curated list without calling Azure API (fast & small)
        return json.dumps({"total": len(_COMMON_PUBLISHERS), "showing": len(_COMMON_PUBLISHERS), "publishers": _COMMON_PUBLISHERS, "hint": "Use search='keyword' to find more publishers from the full Azure catalog."})
    # Search the full list from Azure
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
    raw = azure_rest.list_vm_image_publishers(client.subscription_id, location, token)
    # Extract just the name field and filter
    s = search.lower()
    matched = [{"name": p.get("name", "")} for p in raw if s in p.get("name", "").lower()]
    total = len(matched)
    return json.dumps({"total": total, "showing": min(top, total), "publishers": matched[:top]})


@mcp.tool()
def list_vm_image_offers(location: str, publisher: str, search: str = None, top: int = 25) -> str:
    """List image offers for a specific publisher in a region.

    Args:
        location: Azure region name.
        publisher: Publisher name, e.g. 'Canonical', 'MicrosoftWindowsServer'.
        search: Optional substring filter on offer name (case-insensitive).
        top: Max results to return (default 25).

    Returns JSON with offer names and total count.
    """
    logger.info(f"Tool called: list_vm_image_offers({location}, {publisher}, search={search})")
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
    raw = azure_rest.list_vm_image_offers(client.subscription_id, location, publisher, token)
    # Extract just the name
    offers = [{"name": o.get("name", "")} for o in raw]
    if search:
        s = search.lower()
        offers = [o for o in offers if s in o["name"].lower()]
    total = len(offers)
    return json.dumps({"total": total, "showing": min(top, total), "offers": offers[:top]})


@mcp.tool()
def list_vm_image_skus(location: str, publisher: str, offer: str, search: str = None, top: int = 25) -> str:
    """List image SKUs for a specific publisher and offer in a region.

    Args:
        location: Azure region name.
        publisher: Publisher name, e.g. 'Canonical'.
        offer: Offer name, e.g. 'ubuntu-24_04-lts'.
        search: Optional substring filter on SKU name (case-insensitive).
        top: Max results to return (default 25).

    Returns JSON with SKU names and total count.
    """
    logger.info(f"Tool called: list_vm_image_skus({location}, {publisher}, {offer}, search={search})")
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
    raw = azure_rest.list_vm_image_skus(client.subscription_id, location, publisher, offer, token)
    # Extract just the name
    skus = [{"name": s.get("name", "")} for s in raw]
    if search:
        f = search.lower()
        skus = [s for s in skus if f in s["name"].lower()]
    total = len(skus)
    return json.dumps({"total": total, "showing": min(top, total), "skus": skus[:top]})


@mcp.tool()
def list_disk_types() -> str:
    """List Azure managed disk types with performance and cost descriptions.

    Returns a static JSON array of the available managed disk SKU types.
    Use this to help users choose the right disk type for their workload.
    """
    logger.info("Tool called: list_disk_types()")
    disk_types = [
        {"sku": "Standard_LRS", "name": "Standard HDD (LRS)", "description": "Lowest cost, suitable for backups, dev/test, infrequent access. Up to 500 IOPS."},
        {"sku": "StandardSSD_LRS", "name": "Standard SSD (LRS)", "description": "Better reliability than HDD, good for web servers, light dev/test. Up to 6,000 IOPS."},
        {"sku": "Premium_LRS", "name": "Premium SSD (LRS)", "description": "Production workloads, high performance. Up to 20,000 IOPS. Requires VM sizes that support premium storage."},
        {"sku": "StandardSSD_ZRS", "name": "Standard SSD (ZRS)", "description": "Zone-redundant standard SSD for higher availability across availability zones."},
        {"sku": "Premium_ZRS", "name": "Premium SSD (ZRS)", "description": "Zone-redundant premium SSD for production workloads requiring zone resiliency."},
        {"sku": "PremiumV2_LRS", "name": "Premium SSD v2 (LRS)", "description": "Next-gen premium SSD with customizable IOPS/throughput independent of disk size. Up to 80,000 IOPS."},
        {"sku": "UltraSSD_LRS", "name": "Ultra Disk (LRS)", "description": "Highest performance for IO-intensive workloads (SAP HANA, databases). Up to 160,000 IOPS. Limited region/VM support."},
    ]
    return json.dumps(disk_types)


# ---------------------------------------------------------------------------
# Write / deploy / delete tools (require explicit user confirmation)
# ---------------------------------------------------------------------------

@mcp.tool()
def deploy_template(resource_group: str, deployment_name: str, template_json: str, parameters_json: str = "{}") -> str:
    """Deploy an ARM template (guarded). Set AZ_RUN_DEPLOY=true to allow.

    - `template_json` and `parameters_json` are JSON strings.
    """
    logger.info(f"Tool called: deploy_template({resource_group}, {deployment_name})")
    if os.environ.get("AZ_RUN_DEPLOY", "false").lower() != "true":
        return json.dumps({"error": "Deployments are disabled. Set AZ_RUN_DEPLOY=true to enable."})
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
    template = json.loads(template_json)
    parameters = json.loads(parameters_json)
    # use azure_rest_formcp.deploy_template directly
    res = azure_rest.deploy_template(client.subscription_id, resource_group, deployment_name, token, template, parameters)
    return json.dumps(res)


@mcp.tool()
def delete_deployment(resource_group: str, deployment_name: str) -> str:
    """Delete a deployment record (does not delete resources)."""
    logger.info(f"Tool called: delete_deployment({resource_group}, {deployment_name})")
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
    azure_rest.delete_deployment(client.subscription_id, resource_group, deployment_name, token)
    return json.dumps({"ok": True})


@mcp.tool()
def deploy_vm(resource_group: str,
              vm_name: str,
              location: str = "eastasia",
              vm_size: str = "Standard_D2as_v5",
              admin_username: str = "jack",
              admin_password: str = None,
              nic_id: str = None,
              vnet_name: str = "vnet-jack",
              subnet_name: str = "default",
              no_public_ip: bool = True,
              image_publisher: str = "Canonical",
              image_offer: str = "ubuntu-24_04-lts",
              image_sku: str = "server",
              image_version: str = "latest",
              os_disk_type: str = "Premium_LRS",
              os_disk_size_gb: int = None,
              os_type: str = "linux") -> str:
    """Create a VM with full customization.

    If `nic_id` is provided, use it; otherwise auto-create NIC (and optional public IP) then create VM.

    Image parameters (use list_vm_image_publishers/offers/skus to discover valid values):
        image_publisher: e.g. 'Canonical', 'MicrosoftWindowsServer', 'RedHat'
        image_offer: e.g. 'ubuntu-24_04-lts', 'WindowsServer', 'RHEL'
        image_sku: e.g. 'server', '2022-datacenter-g2', '9_4'
        image_version: e.g. 'latest' or a specific version number

    Disk parameters (use list_disk_types to see options):
        os_disk_type: Managed disk SKU — Premium_LRS, StandardSSD_LRS, Standard_LRS, etc.
        os_disk_size_gb: OS disk size in GB. None = Azure default for the image.

    OS type:
        os_type: 'linux' or 'windows' — controls OS-specific configuration in the VM.
    """
    logger.info(f"Tool called: deploy_vm({resource_group}, {vm_name})")
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)

    if not admin_password:
        admin_password = os.environ.get("AZ_TEST_PASS")
        if not admin_password:
            return json.dumps({"error": "admin_password not provided and AZ_TEST_PASS not set"})

    # Build the image reference from individual parameters
    image_reference = {
        "publisher": image_publisher,
        "offer": image_offer,
        "sku": image_sku,
        "version": image_version,
    }

    try:
        # If nic_id supplied, use direct VM create/update
        if nic_id:
            resp = azure_rest.create_or_update_vm(client.subscription_id, resource_group, vm_name, token, nic_id,
                                                  location=location, vm_size=vm_size,
                                                  admin_username=admin_username, admin_password=admin_password,
                                                  image_reference=image_reference,
                                                  os_disk_type=os_disk_type, os_disk_size_gb=os_disk_size_gb,
                                                  os_type=os_type)
            return json.dumps(resp)

        # Auto-create NIC (and optional public IP)
        public_ip_id = None
        if not no_public_ip:
            public_ip_id = azure_rest.create_public_ip(client.subscription_id, resource_group, vm_name + "-pip", token, location=location)

        # Build subnet id and create NIC
        subnet_id = f"/subscriptions/{client.subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/virtualNetworks/{vnet_name}/subnets/{subnet_name}"
        nic_name = vm_name + "-nic"
        nic_id_created = azure_rest.create_nic(client.subscription_id, resource_group, nic_name, token, subnet_id, public_ip_id, location=location)

        # Create VM using direct compute PUT with the new NIC
        resp = azure_rest.create_or_update_vm(client.subscription_id, resource_group, vm_name, token, nic_id_created,
                                              location=location, vm_size=vm_size,
                                              admin_username=admin_username, admin_password=admin_password,
                                              image_reference=image_reference,
                                              os_disk_type=os_disk_type, os_disk_size_gb=os_disk_size_gb,
                                              os_type=os_type)
        return json.dumps(resp)
    except Exception as ex:
        return json.dumps({"error": str(ex)})


@mcp.tool()
def delete_vm_tool(resource_group: str, vm_name: str, force: bool = True) -> str:
    """Delete a VM resource using the Compute Delete API. Returns operation result or error."""
    logger.info(f"Tool called: delete_vm_tool({resource_group}, {vm_name}, force={force})")
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)
    try:
        res = azure_rest.delete_vm(client.subscription_id, resource_group, vm_name, token, force_deletion=force)
        return json.dumps({"ok": True, "result": res})
    except Exception as ex:
        return json.dumps({"error": str(ex)})
    

if __name__ == "__main__":
    logger.info(f"Starting MCP Server on {host}:{port} (transport={transport})...")
    try:
        # Prefer explicit host/port if supported by the MCP runtime
        if transport in ("streamable_http", "streamable-http", "http"):
            try:
                import uvicorn
                # transport security patched above

                app_candidate = mcp.streamable_http_app
                if callable(app_candidate):
                    app = app_candidate()
                else:
                    app = app_candidate
                # Rewrite Host header to avoid MCP host validation issues
                app = HostRewriteMiddleware(app, host="127.0.0.1:8080")
                logger.info("Serving streamable HTTP endpoint at /mcp")
                uvicorn.run(app, host=host, port=port)
            except Exception:
                # Fallback to mcp.run if uvicorn/app is not available
                try:
                    mcp.run(transport=transport, host=host, port=port)
                except TypeError:
                    mcp.run(transport=transport)
        else:
            try:
                mcp.run(transport=transport, host=host, port=port)
            except TypeError:
                mcp.run(transport=transport)
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        sys.exit(1)
    finally:
        logger.info("Server terminated")

