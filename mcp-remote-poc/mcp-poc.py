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
        "description": "MCP tools exposing Azure VM inspection helpers",
        "tools": {
            "list_vms": "List VMs in a subscription or resource group. Args: resource_group (optional)",
            "list_vms_all": "List all VMs (handles pagination). Args: resource_group (optional)",
            "get_vm_instance_view": "Return VM instanceView JSON. Args: resource_group, vm_name",
            "get_vm_power_state": "Return parsed VM power state (running/stopped). Args: resource_group, vm_name",
            "get_vm_status": "Convenience: returns name, id, location, provisioningState, powerState. Args: resource_group, vm_name",
            "deploy_template": "(Guarded) Deploy an ARM template. Args: resource_group, deployment_name, template_json, parameters_json. Requires AZ_RUN_DEPLOY=true",
            "delete_deployment": "Delete a deployment record. Args: resource_group, deployment_name"
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
              no_public_ip: bool = True) -> str:
    """Create a VM. If `nic_id` is provided, use it; otherwise auto-create NIC (and optional public IP) then create VM.

    All parameters are passed in from the MCP call. `admin_password` may be omitted if your environment
    configures password-based authentication differently.
    """
    logger.info(f"Tool called: deploy_vm({resource_group}, {vm_name})")
    client = _get_client()
    token = azure_rest.get_access_token(client.tenant_id, client.client_id, client.client_secret)

    if not admin_password:
        admin_password = os.environ.get("AZ_TEST_PASS")
        if not admin_password:
            return json.dumps({"error": "admin_password not provided and AZ_TEST_PASS not set"})

    try:
        # If nic_id supplied, use direct VM create/update
        if nic_id:
            resp = azure_rest.create_or_update_vm(client.subscription_id, resource_group, vm_name, token, nic_id,
                                                  location=location, vm_size=vm_size,
                                                  admin_username=admin_username, admin_password=admin_password)
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
                                              admin_username=admin_username, admin_password=admin_password)
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

