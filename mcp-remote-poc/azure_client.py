from typing import Optional, List, Dict, Any
import os
from pathlib import Path
import re
import requests

try:
    # local copy in same folder
    import azure_rest_formcp as azure_rest
except Exception:
    # fallback to parent src package if present
    try:
        from src import azure_rest_formcp as azure_rest
    except Exception:
        azure_rest = None


def _load_dotenv_like(path: Path) -> None:
    """Load simple KEY=VALUE lines from a file into `os.environ` when not already set.

    Supports quoted values and ignores comments/blank lines. Best-effort; does not raise.
    """
    if not path or not path.exists():
        return
    line_re = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                m = line_re.match(line)
                if not m:
                    continue
                key, val = m.group(1), m.group(2)
                # strip optional surrounding quotes
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                val = val.strip()
                if key not in os.environ:
                    os.environ[key] = val
    except Exception:
        return


# Load .env files: first local folder, then project root
_load_dotenv_like(Path(__file__).resolve().parent / ".env")
_load_dotenv_like(Path(__file__).resolve().parent.parent / ".env")


class AzureClient:
    """Minimal Azure credentials wrapper used by `mcp-poc.py`.

    Reads AZ_TENANT_ID, AZ_CLIENT_ID, AZ_CLIENT_SECRET, AZ_SUBSCRIPTION_ID from environment.
    Provides `list_vms_all` and `get_vm_power_state_safe` helpers that delegate to `azure_rest_formcp`.
    """

    def __init__(self, tenant_id: str, client_id: str, client_secret: str, subscription_id: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.subscription_id = subscription_id

    @classmethod
    def from_env(cls) -> "AzureClient":
        tenant = os.environ.get("AZ_TENANT_ID")
        client_id = os.environ.get("AZ_CLIENT_ID")
        client_secret = os.environ.get("AZ_CLIENT_SECRET")
        subscription = os.environ.get("AZ_SUBSCRIPTION_ID")
        if not all([tenant, client_id, client_secret, subscription]):
            raise RuntimeError("Missing Azure credentials in environment: AZ_TENANT_ID, AZ_CLIENT_ID, AZ_CLIENT_SECRET, AZ_SUBSCRIPTION_ID")
        return cls(tenant, client_id, client_secret, subscription)

    def list_vms_all(self, resource_group: Optional[str] = None) -> List[Dict[str, Any]]:
        if azure_rest is None:
            raise RuntimeError("azure_rest_formcp module not found")
        token = azure_rest.get_access_token(self.tenant_id, self.client_id, self.client_secret)
        first = azure_rest.list_vms(self.subscription_id, token, resource_group)
        vms = list(first.get("value", []))
        next_link = first.get("nextLink") or first.get("odata.nextLink")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        while next_link:
            r = requests.get(next_link, headers=headers)
            r.raise_for_status()
            j = r.json()
            vms.extend(j.get("value", []))
            next_link = j.get("nextLink") or j.get("odata.nextLink")
        return vms

    def get_vm_power_state_safe(self, resource_group: str, vm_name: str) -> Optional[str]:
        if azure_rest is None:
            return None
        try:
            token = azure_rest.get_access_token(self.tenant_id, self.client_id, self.client_secret)
            iv = azure_rest.get_vm_instance_view(self.subscription_id, resource_group, vm_name, token)
            return azure_rest.get_vm_power_state(iv)
        except Exception:
            return None
from typing import Optional, List, Dict, Any
import os
from pathlib import Path
import re
import requests

try:
	# local copy in same folder
	import azure_rest_formcp as azure_rest
except Exception:
	# fallback to parent src package if present
	try:
		from src import azure_rest_formcp as azure_rest
	except Exception:
		azure_rest = None


def _load_dotenv_like(path: Path) -> None:
	"""Load simple KEY=VALUE lines from a file into `os.environ` when not already set.

	Supports quoted values and ignores comments/blank lines. Best-effort; does not raise.
	"""
	if not path or not path.exists():
		return
	line_re = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")
	try:
		with path.open("r", encoding="utf-8") as f:
			for raw in f:
				line = raw.strip()
				if not line or line.startswith("#"):
					continue
				m = line_re.match(line)
				if not m:
					continue
				key, val = m.group(1), m.group(2)
				# strip optional surrounding quotes
				if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
					val = val[1:-1]
				val = val.strip()
				if key not in os.environ:
					os.environ[key] = val
	except Exception:
		return


# Load .env files: first local folder, then project root
_load_dotenv_like(Path(__file__).resolve().parent / ".env")
_load_dotenv_like(Path(__file__).resolve().parent.parent / ".env")


class AzureClient:
	"""Minimal Azure credentials wrapper used by `mcp-poc.py`.

	Reads AZ_TENANT_ID, AZ_CLIENT_ID, AZ_CLIENT_SECRET, AZ_SUBSCRIPTION_ID from environment.
	Provides `list_vms_all` and `get_vm_power_state_safe` helpers that delegate to `azure_rest_formcp`.
	"""

	def __init__(self, tenant_id: str, client_id: str, client_secret: str, subscription_id: str):
		self.tenant_id = tenant_id
		self.client_id = client_id
		self.client_secret = client_secret
		self.subscription_id = subscription_id

	@classmethod
	def from_env(cls) -> "AzureClient":
		tenant = os.environ.get("AZ_TENANT_ID")
		client_id = os.environ.get("AZ_CLIENT_ID")
		client_secret = os.environ.get("AZ_CLIENT_SECRET")
		subscription = os.environ.get("AZ_SUBSCRIPTION_ID")
		if not all([tenant, client_id, client_secret, subscription]):
			raise RuntimeError("Missing Azure credentials in environment: AZ_TENANT_ID, AZ_CLIENT_ID, AZ_CLIENT_SECRET, AZ_SUBSCRIPTION_ID")
		return cls(tenant, client_id, client_secret, subscription)

	def list_vms_all(self, resource_group: Optional[str] = None) -> List[Dict[str, Any]]:
		if azure_rest is None:
			raise RuntimeError("azure_rest_formcp module not found")
		token = azure_rest.get_access_token(self.tenant_id, self.client_id, self.client_secret)
		first = azure_rest.list_vms(self.subscription_id, token, resource_group)
		vms = list(first.get("value", []))
		next_link = first.get("nextLink") or first.get("odata.nextLink")
		headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
		while next_link:
			r = requests.get(next_link, headers=headers)
			r.raise_for_status()
			j = r.json()
			vms.extend(j.get("value", []))
			next_link = j.get("nextLink") or j.get("odata.nextLink")
		return vms

	def get_vm_power_state_safe(self, resource_group: str, vm_name: str) -> Optional[str]:
		if azure_rest is None:
			return None
		try:
			token = azure_rest.get_access_token(self.tenant_id, self.client_id, self.client_secret)
			iv = azure_rest.get_vm_instance_view(self.subscription_id, resource_group, vm_name, token)
			return azure_rest.get_vm_power_state(iv)
		except Exception:
			return None

from typing import Optional, List, Dict, Any
import os
from pathlib import Path
import re
import requests

try:
	# local copy in same folder
	import azure_rest_formcp as azure_rest
except Exception:
	# fallback to parent src package if present
	try:
		from src import azure_rest_formcp as azure_rest
	except Exception:
		azure_rest = None


def _load_dotenv_like(path: Path) -> None:
	"""Load simple KEY=VALUE lines from a file into `os.environ` when not already set.

	Supports quoted values and ignores comments/blank lines. Best-effort; does not raise.
	"""
	if not path or not path.exists():
		return
	line_re = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")
	try:
		with path.open("r", encoding="utf-8") as f:
			for raw in f:
				line = raw.strip()
				if not line or line.startswith("#"):
					continue
				m = line_re.match(line)
				if not m:
					continue
				key, val = m.group(1), m.group(2)
				# strip optional surrounding quotes
				if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
					val = val[1:-1]
				val = val.strip()
				if key not in os.environ:
					os.environ[key] = val
	except Exception:
		return


# Load .env files: first local folder, then project root
_load_dotenv_like(Path(__file__).resolve().parent / ".env")
_load_dotenv_like(Path(__file__).resolve().parent.parent / ".env")


class AzureClient:
	"""Minimal Azure credentials wrapper used by `mcp-poc.py`.

	Reads AZ_TENANT_ID, AZ_CLIENT_ID, AZ_CLIENT_SECRET, AZ_SUBSCRIPTION_ID from environment.
	Provides `list_vms_all` and `get_vm_power_state_safe` helpers that delegate to `azure_rest_formcp`.
	"""

	def __init__(self, tenant_id: str, client_id: str, client_secret: str, subscription_id: str):
		self.tenant_id = tenant_id
		self.client_id = client_id
		self.client_secret = client_secret
		self.subscription_id = subscription_id

	@classmethod
	def from_env(cls) -> "AzureClient":
		tenant = os.environ.get("AZ_TENANT_ID")
		client_id = os.environ.get("AZ_CLIENT_ID")
		client_secret = os.environ.get("AZ_CLIENT_SECRET")
		subscription = os.environ.get("AZ_SUBSCRIPTION_ID")
		if not all([tenant, client_id, client_secret, subscription]):
			raise RuntimeError("Missing Azure credentials in environment: AZ_TENANT_ID, AZ_CLIENT_ID, AZ_CLIENT_SECRET, AZ_SUBSCRIPTION_ID")
		return cls(tenant, client_id, client_secret, subscription)

	def list_vms_all(self, resource_group: Optional[str] = None) -> List[Dict[str, Any]]:
		if azure_rest is None:
			raise RuntimeError("azure_rest_formcp module not found")
		token = azure_rest.get_access_token(self.tenant_id, self.client_id, self.client_secret)
		first = azure_rest.list_vms(self.subscription_id, token, resource_group)
		vms = list(first.get("value", []))
		next_link = first.get("nextLink") or first.get("odata.nextLink")
		headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
		while next_link:
			r = requests.get(next_link, headers=headers)
			r.raise_for_status()
			j = r.json()
			vms.extend(j.get("value", []))
			next_link = j.get("nextLink") or j.get("odata.nextLink")
		return vms

	def get_vm_power_state_safe(self, resource_group: str, vm_name: str) -> Optional[str]:
		if azure_rest is None:
			return None
		try:
			token = azure_rest.get_access_token(self.tenant_id, self.client_id, self.client_secret)
			iv = azure_rest.get_vm_instance_view(self.subscription_id, resource_group, vm_name, token)
			return azure_rest.get_vm_power_state(iv)
		except Exception:
			return None


