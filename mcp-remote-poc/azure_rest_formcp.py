"""
Lightweight Azure Resource Manager REST helpers (API-only).
Requires: requests

Provides:
- get_access_token: client credentials flow
- list_vms: list VMs in a subscription or resource group
- get_vm_instance_view: instance view (power state + statuses)
- get_vm_power_state: parse power state from instance view
- deploy_template: create/update a Resource Manager deployment (use to create VM via template)
- delete_deployment: remove a deployment

Usage: see examples.py and README.md
"""
from typing import Optional, Dict, Any
import requests
import os
import json

DEFAULT_API_VERSION = "2024-11-01"
MANAGEMENT_ENDPOINT = "https://management.azure.com"


def get_access_token(tenant_id: str, client_id: str, client_secret: str, scope: str = "https://management.azure.com/.default") -> str:
    """Obtain an OAuth2 token using client credentials.
    Returns the bearer token string (not prefixed).
    """
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope,
    }
    r = requests.post(url, data=data)
    r.raise_for_status()
    j = r.json()
    return j["access_token"]


def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def list_vms(subscription_id: str, token: str, resource_group: Optional[str] = None, api_version: str = DEFAULT_API_VERSION) -> Dict[str, Any]:
    """List virtual machines. If resource_group is None, lists across subscription.

    Returns the parsed JSON response.
    """
    if resource_group:
        url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Compute/virtualMachines?api-version={api_version}"
    else:
        url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/providers/Microsoft.Compute/virtualMachines?api-version={api_version}"
    r = requests.get(url, headers=_headers(token))
    r.raise_for_status()
    return r.json()


def get_vm_instance_view(subscription_id: str, resource_group: str, vm_name: str, token: str, api_version: str = DEFAULT_API_VERSION) -> Dict[str, Any]:
    """Get instanceView for a VM which contains statuses (power state etc.)

    Returns the parsed JSON response.
    """
    url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Compute/virtualMachines/{vm_name}/instanceView?api-version={api_version}"
    r = requests.get(url, headers=_headers(token))
    r.raise_for_status()
    return r.json()


def get_vm_power_state(instance_view: Dict[str, Any]) -> Optional[str]:
    """Extract power state string (e.g., 'running', 'stopped') from instanceView JSON.
    Returns None if not found.
    """
    statuses = instance_view.get("statuses") or []
    for s in statuses:
        code = s.get("code", "")
        # Codes are like 'PowerState/running'
        if code.startswith("PowerState/"):
            return code.split("/", 1)[1]
    return None


def deploy_template(subscription_id: str, resource_group: str, deployment_name: str, token: str, template: Dict[str, Any], parameters: Optional[Dict[str, Any]] = None, mode: str = "Incremental") -> Dict[str, Any]:
    """Create or update a deployment in a resource group using an ARM template.

    - `template` should be a dict representing the ARM template JSON.
    - `parameters` should be a dict of parameter values (not the full param wrapper), e.g. {"vmName": {"value": "myvm"}}

    Returns the deployment operation response JSON.
    """
    url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourcegroups/{resource_group}/providers/Microsoft.Resources/deployments/{deployment_name}?api-version=2021-04-01"
    body = {"properties": {"mode": mode, "template": template, "parameters": parameters or {}}}
    r = requests.put(url, headers=_headers(token), json=body)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError:
        # Print response details to help diagnose 403/authorization errors
        try:
            print("create_or_update_vm HTTP error response:", json.dumps(r.json(), indent=2))
        except Exception:
            print("create_or_update_vm HTTP error response text:", r.text)
        raise
    return r.json()


def build_basic_vm_template(vm_name: str, location: str = "eastasia", admin_username: str = "jack", admin_password: str = "Jackyim1997!", vm_size: str = "Standard_D2as_v5", vnet_name: str = "vnet-jack", subnet_name: str = "default") -> Dict[str, Any]:
    """Return a minimal ARM template (as dict) that creates a public IP, network interface,
    and a single Ubuntu VM. This template assumes the resource group exists. It will
    reference the provided vnet/subnet by name (creates NIC attached to that subnet).

    NOTE: Deploying this will create billable resources. Use a test subscription and
    ensure credentials/permissions are correct.
    """
    template = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {},
        "variables": {"vmName": vm_name, "vnetName": vnet_name, "subnetName": subnet_name, "publicIpName": vm_name + "-pip", "nicName": vm_name + "-nic"},
        "resources": [
            {
                "type": "Microsoft.Network/publicIPAddresses",
                "apiVersion": "2021-02-01",
                "name": "[variables('publicIpName')]",
                "location": location,
                "properties": {"publicIPAllocationMethod": "Dynamic"}
            },
            {
                "type": "Microsoft.Network/networkInterfaces",
                "apiVersion": "2021-02-01",
                "name": "[variables('nicName')]",
                "location": location,
                "dependsOn": ["[resourceId('Microsoft.Network/publicIPAddresses', variables('publicIpName'))]"],
                "properties": {
                    "ipConfigurations": [
                        {
                            "name": "ipconfig1",
                            "properties": {
                                "subnet": {"id": "[resourceId('Microsoft.Network/virtualNetworks/subnets', variables('vnetName'), variables('subnetName'))]"},
                                "privateIPAllocationMethod": "Dynamic",
                                "publicIPAddress": {"id": "[resourceId('Microsoft.Network/publicIPAddresses', variables('publicIpName'))]"}
                            }
                        }
                    ]
                }
            },
            {
                "type": "Microsoft.Compute/virtualMachines",
                "apiVersion": "2021-07-01",
                "name": "[variables('vmName')]",
                "location": location,
                "dependsOn": ["[resourceId('Microsoft.Network/networkInterfaces', variables('nicName'))]"],
                "properties": {
                    "hardwareProfile": {"vmSize": vm_size},
                    "osProfile": {
                        "computerName": "[variables('vmName')]",
                        "adminUsername": admin_username,
                        "adminPassword": admin_password,
                        "linuxConfiguration": {"disablePasswordAuthentication": False}
                    },
                    "networkProfile": {"networkInterfaces": [{"id": "[resourceId('Microsoft.Network/networkInterfaces', variables('nicName'))]"}]},
                    "storageProfile": {
                        "imageReference": {"publisher": "Canonical", "offer": "UbuntuServer", "sku": "18.04-LTS", "version": "latest"},
                        "osDisk": {"createOption": "FromImage"}
                    }
                }
            }
        ],
        "outputs": {}
    }
    return template


def create_or_update_vm(
    subscription_id: str,
    resource_group: str,
    vm_name: str,
    token: str,
    nic_id: str,
    location: str = "eastasia",
    vm_size: str = "Standard_D2as_v5",
    admin_username: str = "jack",
    admin_password: str = "Jackyim1997!",
    image_reference: Optional[Dict[str, str]] = None,
    os_disk_name: Optional[str] = None,
    api_version: str = "2025-04-01",
) -> Dict[str, Any]:
    """Create or update a VM by calling the Compute "Create Or Update" REST API (PUT).

    This follows the official sample payload (including linuxConfiguration.patchSettings.patchMode).
    It requires an existing NIC id (nic_id). Returns the parsed JSON response.
    """
    if not nic_id:
        raise ValueError("nic_id is required to create a VM with this helper")

    image_reference = image_reference or {"publisher": "Canonical", "offer": "UbuntuServer", "sku": "18.04-LTS", "version": "latest"}
    os_disk_name = os_disk_name or f"{vm_name}-osdisk"

    url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Compute/virtualMachines/{vm_name}?api-version={api_version}"

    body = {
        "location": location,
        "properties": {
            "hardwareProfile": {"vmSize": vm_size},
            "storageProfile": {
                "imageReference": image_reference,
                "osDisk": {
                    "caching": "ReadWrite",
                    "managedDisk": {"storageAccountType": "Premium_LRS"},
                    "name": os_disk_name,
                    "createOption": "FromImage",
                },
            },
            "osProfile": {
                "adminUsername": admin_username,
                "computerName": vm_name,
                "adminPassword": admin_password,
                "linuxConfiguration": {
                    "provisionVMAgent": True,
                    "patchSettings": {"patchMode": "ImageDefault"},
                },
            },
            "networkProfile": {"networkInterfaces": [{"id": nic_id, "properties": {"primary": True}}]},
        },
    }

    r = requests.put(url, headers=_headers(token), json=body)
    r.raise_for_status()
    return r.json()


def create_public_ip(subscription_id: str, resource_group: str, name: str, token: str, location: str = "eastasia", api_version: str = "2021-02-01") -> str:
    url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/publicIPAddresses/{name}?api-version={api_version}"
    body = {"location": location, "properties": {"publicIPAllocationMethod": "Dynamic"}}

    r = requests.put(url, headers=_headers(token), json=body)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError:
        # Try to detect a Basic SKU quota error and fall back to Standard SKU
        err_code = None
        try:
            err = r.json().get("error", {})
            err_code = err.get("code")
        except Exception:
            pass
        if err_code == "IPv4BasicSkuPublicIpCountLimitReached":
            print("Basic SKU public IP quota reached; attempting to create a Standard SKU public IP instead...")
            body_std = {"location": location, "sku": {"name": "Standard"}, "properties": {"publicIPAllocationMethod": "Static"}}
            r2 = requests.put(url, headers=_headers(token), json=body_std)
            try:
                r2.raise_for_status()
                j2 = r2.json()
                return j2.get("id") or f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/publicIPAddresses/{name}"
            except Exception:
                try:
                    print("create_public_ip (Standard) HTTP error response:", json.dumps(r2.json(), indent=2))
                except Exception:
                    print("create_public_ip (Standard) HTTP error response text:", r2.text)
                raise
        # otherwise print original error and re-raise
        try:
            print("create_public_ip HTTP error response:", json.dumps(r.json(), indent=2))
        except Exception:
            print("create_public_ip HTTP error response text:", r.text)
        raise

    j = r.json()
    return j.get("id") or f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/publicIPAddresses/{name}"


def create_vnet_with_subnet(subscription_id: str, resource_group: str, vnet_name: str, subnet_name: str, token: str, location: str = "eastasia", api_version: str = "2021-02-01") -> str:
    url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/virtualNetworks/{vnet_name}?api-version={api_version}"
    body = {
        "location": location,
        "properties": {
            "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
            "subnets": [{"name": subnet_name, "properties": {"addressPrefix": "10.0.0.0/24"}}],
        },
    }
    r = requests.put(url, headers=_headers(token), json=body)
    r.raise_for_status()
    # return subnet resource id (must start with '/subscriptions/...')
    return f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/virtualNetworks/{vnet_name}/subnets/{subnet_name}"


def create_nic(subscription_id: str, resource_group: str, nic_name: str, token: str, subnet_id: str, public_ip_id: Optional[str] = None, location: str = "eastasia", api_version: str = "2021-02-01") -> str:
    url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/networkInterfaces/{nic_name}?api-version={api_version}"
    ip_conf = {"name": "ipconfig1", "properties": {"subnet": {"id": subnet_id}, "privateIPAllocationMethod": "Dynamic"}}
    if public_ip_id:
        ip_conf["properties"]["publicIPAddress"] = {"id": public_ip_id}
    body = {"location": location, "properties": {"ipConfigurations": [ip_conf]}}
    r = requests.put(url, headers=_headers(token), json=body)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError:
        try:
            print("create_nic HTTP error response:", json.dumps(r.json(), indent=2))
        except Exception:
            print("create_nic HTTP error response text:", r.text)
        raise
    j = r.json()
    return j.get("id") or f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/networkInterfaces/{nic_name}"


def delete_deployment(subscription_id: str, resource_group: str, deployment_name: str, token: str) -> None:
    url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourcegroups/{resource_group}/providers/Microsoft.Resources/deployments/{deployment_name}?api-version=2021-04-01"
    r = requests.delete(url, headers=_headers(token))
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError:
        try:
            print("delete_deployment HTTP error response:", json.dumps(r.json(), indent=2))
        except Exception:
            print("delete_deployment HTTP error response text:", r.text)
        raise


def delete_vm(subscription_id: str, resource_group: str, vm_name: str, token: str, force_deletion: bool = True, api_version: str = "2025-04-01", timeout: int = 300, poll_interval: int = 5) -> Optional[Dict[str, Any]]:
    """Delete a virtual machine using the Compute Delete REST API.

    If `force_deletion` is True the query `forceDeletion=true` will be appended.
    Handles async 202 responses by polling the `Azure-AsyncOperation` or `Location` URL
    until the operation reports a terminal status or the timeout is reached.

    Returns the final operation JSON (when available) or None on immediate success.
    Raises on HTTP errors or if the async operation reports failure/timeout.
    """
    import time

    url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Compute/virtualMachines/{vm_name}?api-version={api_version}"
    if force_deletion:
        url = url + "&forceDeletion=true"

    r = requests.delete(url, headers=_headers(token))
    try:
        # Immediate success (204 No Content or 200 OK)
        if r.status_code in (200, 204):
            try:
                return r.json() if r.text else None
            except Exception:
                return None

        # Async operation started
        if r.status_code == 202:
            async_url = r.headers.get("Azure-AsyncOperation") or r.headers.get("Location")
            if not async_url:
                # No operation URL to poll; return raw response
                return None

            end_time = time.time() + timeout
            while time.time() < end_time:
                pr = requests.get(async_url, headers=_headers(token))
                try:
                    pr.raise_for_status()
                except Exception:
                    print("delete_vm: failed fetching async status", pr.status_code, pr.text)
                    time.sleep(poll_interval)
                    continue
                pj = pr.json()
                status = pj.get("status") or pj.get("properties", {}).get("status") or pj.get("properties", {}).get("provisioningState")
                if status in ("Succeeded", "succeeded"):
                    return pj
                if status in ("Failed", "failed"):
                    print("delete_vm: async operation failed:", json.dumps(pj, indent=2))
                    raise Exception("VM delete operation failed")
                time.sleep(poll_interval)
            raise TimeoutError("Timed out waiting for VM delete async operation")

        # Other non-success status -> raise with diagnostics
        r.raise_for_status()
    except requests.exceptions.HTTPError:
        try:
            print("delete_vm HTTP error response:", json.dumps(r.json(), indent=2))
        except Exception:
            print("delete_vm HTTP error response text:", r.text)
        raise


if __name__ == "__main__":
    # Simple interactive test runner for the module.
    # It will only run live calls when required environment variables are set.
    import json
    import time
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parent / ".env")
    print("Azure REST helpers - quick test runner (will not print secrets).")

    tenant = os.environ.get("AZ_TENANT_ID")
    client_id = os.environ.get("AZ_CLIENT_ID")
    client_secret = os.environ.get("AZ_CLIENT_SECRET")
    subscription_id = os.environ.get("AZ_SUBSCRIPTION_ID")

    if not all([tenant, client_id, client_secret, subscription_id]):
        print(
            "Missing one or more required env vars: AZ_TENANT_ID, AZ_CLIENT_ID, AZ_CLIENT_SECRET, AZ_SUBSCRIPTION_ID."
        )
        print("Set them in your environment or .env and re-run to perform live tests.")
        raise SystemExit(1)

    # 1) Acquire token (print full token endpoint response with token masked)
    print("[1/4] Acquiring access token (full response will be printed with token masked)...")
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://management.azure.com/.default",
    }
    try:
        r = requests.post(token_url, data=data)
        r.raise_for_status()
        token_json = r.json()
    except Exception as ex:
        print("  - token endpoint request failed:", ex)
        raise

    # Mask the access token when printing
    token_json_masked = dict(token_json)
    if "access_token" in token_json_masked:
        token_json_masked["access_token"] = "<masked>"
    print("  - token endpoint response:")
    print(json.dumps(token_json_masked, indent=2))
    token = token_json.get("access_token")
    if not token:
        print("  - no access_token found in response; aborting")
        raise SystemExit(1)

    # 2) List VMs
    print("[2/4] Listing VMs in subscription (full response will be printed)...")
    try:
        # perform the same request as `list_vms` but capture full response
        url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/providers/Microsoft.Compute/virtualMachines?api-version={DEFAULT_API_VERSION}"
        r = requests.get(url, headers=_headers(token))
        r.raise_for_status()
        resp = r.json()
        vm_list = resp.get("value", [])
        print("  - list_vms response JSON:")
        print(json.dumps(resp, indent=2))
    except Exception as ex:
        print("  - list_vms failed:", ex)
        vm_list = []

    # helper to parse resource group and vm name from a VM id
    def parse_rg_and_name(vm: dict):
        vid = vm.get("id", "")
        parts = [p for p in vid.split("/") if p]
        try:
            rg_idx = parts.index("resourceGroups")
            rg = parts[rg_idx + 1]
            name = parts[-1]
            return rg, name
        except Exception:
            return None, None

    # 3) Get instance view and power state for first VM (if any)
    print("[3/4] Getting instance view and power state for first VM (if available)...")
    if vm_list:
        rg, name = parse_rg_and_name(vm_list[0])
        if not rg or not name:
            print(f"  - could not parse resource group/name from vm id: {vm_list[0].get('id')}")
        else:
            try:
                # call instanceView and print full JSON
                url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{name}/instanceView?api-version={DEFAULT_API_VERSION}"
                r = requests.get(url, headers=_headers(token))
                r.raise_for_status()
                iv = r.json()
                state = get_vm_power_state(iv)
                print(f"  - VM {name} (rg={rg}) power state: {state}")
                print("  - instanceView JSON:")
                print(json.dumps(iv, indent=2))
            except Exception as ex:
                print(f"  - failed to get instance view for {name} in {rg}: {ex}")
    else:
        print("  - no VMs returned; skipping instance view test")

    # 4) Optional: deploy a minimal template (guarded by AZ_RUN_DEPLOY and AZ_TEST_RESOURCE_GROUP)
    run_deploy = os.environ.get("AZ_RUN_DEPLOY", "false").lower() == "true"
    if run_deploy:
        # Default to resource group 'poc' when AZ_TEST_RESOURCE_GROUP is not provided
        rg = os.environ.get("AZ_TEST_RESOURCE_GROUP", "poc")
        if not rg:
            print("AZ_RUN_DEPLOY=true but AZ_TEST_RESOURCE_GROUP not set — defaulting to 'poc'")
            rg = "poc"
        else:
            # Allow skipping VM creation while still running post-deploy steps
            # Allow a single env var to specify the VM name for create/delete steps
            default_vm_name = os.environ.get("AZ_TARGET_VM_NAME") or os.environ.get("AZ_TEST_VM_NAME", "DeployByfoundryAgent")
            creation_skipped = os.environ.get("AZ_SKIP_CREATE_VM", "false").lower() == "true"
            if creation_skipped:
                print("[4/4] AZ_SKIP_CREATE_VM=true — skipping VM creation step (no VM will be created).")
            else:
                # Prefer direct VM create/update (PUT) when an existing NIC id is provided.
                nic_id = os.environ.get("AZ_TEST_NIC_ID")
                # If nic_id is provided but the NIC resource doesn't exist, ignore it and fall back
                if nic_id:
                    # nic_id may be a full resource id starting with '/subscriptions' or a URL
                    if nic_id.startswith("/"):
                        nic_url = MANAGEMENT_ENDPOINT + nic_id + "?api-version=2021-02-01"
                    elif nic_id.lower().startswith("http"):
                        nic_url = nic_id if "?" in nic_id else nic_id + "?api-version=2021-02-01"
                    else:
                        # assume name only in the target resource group
                        nic_url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{rg}/providers/Microsoft.Network/networkInterfaces/{nic_id}?api-version=2021-02-01"
                    try:
                        nr = requests.get(nic_url, headers=_headers(token))
                        if nr.status_code != 200:
                            print(f"  - AZ_TEST_NIC_ID provided but NIC not found (status {nr.status_code}), will auto-create NIC instead")
                            nic_id = None
                    except Exception:
                        print("  - failed to verify AZ_TEST_NIC_ID existence; will auto-create NIC")
                        nic_id = None
                vm_name = default_vm_name
                if not creation_skipped and nic_id:
                    print(f"[4/4] Creating VM {vm_name} in {rg} via Compute PUT using NIC {nic_id} (api-version=2025-04-01)")
                    try:
                        vm_resp = create_or_update_vm(
                            subscription_id=subscription_id,
                            resource_group=rg,
                            vm_name=vm_name,
                            token=token,
                            nic_id=nic_id,
                            location=os.environ.get("AZ_TEST_LOCATION", "eastasia"),
                            vm_size=os.environ.get("AZ_TEST_VM_SIZE", "Standard_D2as_v5"),
                            admin_username=os.environ.get("AZ_TEST_ADMIN", "jack"),
                            admin_password=os.environ.get("AZ_TEST_PASS", "Jackyim1997!"),
                        )
                        print("  - create_or_update_vm response JSON:")
                        print(json.dumps(vm_resp, indent=2))
                    except Exception as ex:
                        print("  - create_or_update_vm failed:", ex)
                else:
                    # Auto-create networking resources (public IP, VNet/subnet if missing, NIC) and create VM
                    vm_name = default_vm_name
                    location = os.environ.get("AZ_TEST_LOCATION", "eastasia")
                    # default to the existing vnet name used in your environment
                    vnet_name = os.environ.get("AZ_TEST_VNET_NAME", "vnet-jack")
                    subnet_name = os.environ.get("AZ_TEST_SUBNET_NAME", "default")
                    public_ip_name = vm_name + "-pip"
                    nic_name = vm_name + "-nic"

                print(f"[4/4] No NIC provided; creating Public IP, VNet (if needed), and NIC in {rg}")
                try:
                    # Ensure vnet/subnet exists (create if not)
                    vnet_url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}?api-version=2021-02-01"
                    vnet_exists = False
                    try:
                        vresp = requests.get(vnet_url, headers=_headers(token))
                        if vresp.status_code == 200:
                            vnet_exists = True
                    except Exception:
                        vnet_exists = False

                    if not vnet_exists:
                        print(f"  - expected vNet {vnet_name} not found in resource group {rg}; aborting (set AZ_TEST_VNET_NAME to an existing vnet or create the vnet first)")
                        raise RuntimeError(f"vNet {vnet_name} not found in resource group {rg}")
                    else:
                        subnet_id = f"/subscriptions/{subscription_id}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}/subnets/{subnet_name}"

                    # create public ip? default: skip public IP to create internal-only NIC
                    no_public_ip = os.environ.get("AZ_TEST_NO_PUBLIC_IP", "true").lower() == "true"
                    public_ip_id = None
                    if not no_public_ip:
                        print(f"  - creating public IP {public_ip_name}")
                        public_ip_id = create_public_ip(subscription_id, rg, public_ip_name, token, location=location)

                    # create nic (attach public IP only if created)
                    print(f"  - creating NIC {nic_name} (public_ip_attached={public_ip_id is not None})")
                    nic_id_created = create_nic(subscription_id, rg, nic_name, token, subnet_id, public_ip_id, location=location)

                    print(f"  - created NIC id: {nic_id_created}")

                    # create VM using an ARM deployment that references the newly created NIC
                    try:
                        deployment_name = f"test-deploy-{int(time.time())}"
                        vm_template = {
                            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
                            "contentVersion": "1.0.0.0",
                            "resources": [
                                {
                                    "type": "Microsoft.Compute/virtualMachines",
                                    "apiVersion": "2025-04-01",
                                    "name": vm_name,
                                    "location": location,
                                    "properties": {
                                        "hardwareProfile": {"vmSize": os.environ.get("AZ_TEST_VM_SIZE", "Standard_D2as_v5")},
                                        "storageProfile": {
                                            "imageReference": {"publisher": "Canonical", "offer": "UbuntuServer", "sku": "18.04-LTS", "version": "latest"},
                                            "osDisk": {"createOption": "FromImage", "name": f"{vm_name}-osdisk", "caching": "ReadWrite", "managedDisk": {"storageAccountType": "Premium_LRS"}}
                                        },
                                        "osProfile": {
                                            "adminUsername": os.environ.get("AZ_TEST_ADMIN", "jack"),
                                            "computerName": vm_name,
                                            "adminPassword": os.environ.get("AZ_TEST_PASS", "Jackyim1997!"),
                                            "linuxConfiguration": {"provisionVMAgent": True, "patchSettings": {"patchMode": "ImageDefault"}}
                                        },
                                        "networkProfile": {"networkInterfaces": [{"id": nic_id_created, "properties": {"primary": True}}]}
                                    }
                                }
                            ],
                        }

                        print(f"  - deploying VM via deployment {deployment_name} referencing NIC {nic_id_created}")
                        deploy_res = deploy_template(subscription_id, rg, deployment_name, token, vm_template, parameters={})
                        print("  - deployment start response:")
                        print(json.dumps(deploy_res, indent=2))

                        # poll deployment until terminal state (reuse earlier polling logic)
                        url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourcegroups/{rg}/providers/Microsoft.Resources/deployments/{deployment_name}?api-version=2021-04-01"
                        terminal_states = ("Succeeded", "Failed", "Canceled")
                        timeout = 900
                        print("  - polling deployment until terminal state (timeout %ds)..." % timeout)
                        end_time = time.time() + timeout
                        final_state = None
                        while time.time() < end_time:
                            pr = requests.get(url, headers=_headers(token))
                            try:
                                pr.raise_for_status()
                                pj = pr.json()
                            except Exception as ex:
                                print("    - error fetching deployment status:", ex)
                                time.sleep(5)
                                continue
                            state = pj.get("properties", {}).get("provisioningState")
                            print(f"    provisioningState={state}")
                            if state in terminal_states:
                                final_state = state
                                break
                            time.sleep(5)

                        if not final_state:
                            print("  - timed out waiting for deployment to finish; leaving deployment record for inspection")
                        else:
                            print("  - deployment reached terminal state:", final_state)
                            if final_state != "Succeeded":
                                # construct operations URL correctly (avoid appending to an existing query string)
                                base_deploy_url = f"{MANAGEMENT_ENDPOINT}/subscriptions/{subscription_id}/resourceGroups/{rg}/providers/Microsoft.Resources/deployments/{deployment_name}"
                                ops_url = f"{base_deploy_url}/operations?api-version=2021-04-01"
                                try:
                                    ops_r = requests.get(ops_url, headers=_headers(token))
                                    ops_r.raise_for_status()
                                    ops_json = ops_r.json()
                                    print("  - deployment operations:")
                                    print(json.dumps(ops_json, indent=2))
                                    # Also try to show top-level deployment error if present
                                    dep_err = pj.get("properties", {}).get("error")
                                    if dep_err:
                                        print("  - deployment error:")
                                        print(json.dumps(dep_err, indent=2))
                                except Exception as ex:
                                    print("  - failed to fetch deployment operations:", ex)

                            # attempt to delete the deployment record
                            try:
                                dr = requests.delete(url, headers=_headers(token))
                                dr.raise_for_status()
                                print("  - deleted deployment record; delete response status:", dr.status_code)
                            except Exception as ex:
                                print("  - failed to delete deployment record:", ex)
                    except Exception as ex:
                        print("  - network resource creation or deployment failed:", ex)

                except Exception as ex:
                    print("  - network resource creation or VM creation failed:", ex)
    else:
        print("Skipping deployment test. Set AZ_RUN_DEPLOY=true and AZ_TEST_RESOURCE_GROUP to enable.")

    # Optional post-run: delete a named deployment record (does not delete VM/resources)
    if run_deploy:
        delete_deploy = os.environ.get("AZ_DELETE_DEPLOYMENT", "false").lower() == "true"
        if delete_deploy:
            del_name = os.environ.get("AZ_DELETE_DEPLOYMENT_NAME", default_vm_name)
            # Use delete_vm helper to remove the VM resource (not the deployment record)
            force_flag = os.environ.get("AZ_DELETE_VM_FORCE", "true").lower() == "true"
            print(f"[5/5] AZ_DELETE_DEPLOYMENT=true — deleting VM '{del_name}' in {rg} (force={force_flag})")
            try:
                delete_vm(subscription_id, rg, del_name, token, force_deletion=force_flag)
                print(f"  - deleted VM resource '{del_name}' (or operation completed)")
            except Exception as ex:
                print(f"  - failed to delete VM '{del_name}':", ex)

    print("Test runner completed.")
