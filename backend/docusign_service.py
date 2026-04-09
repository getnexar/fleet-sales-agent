"""
DocuSign e-signature service for Nexar Fleet quote agreements.

Authentication: JWT Grant (RS256 RSA key impersonation).
Envelope strategy: template-based with text tab merge fields.
Signing URL: recipient embedded view — returned directly to the chat widget.

Required secrets in Secret Manager (or env vars for local dev):
  fleet-docusign-rsa-private-key   → RSA private key PEM string
  fleet-docusign-integration-key   → DocuSign app Integration Key UUID
  fleet-docusign-user-id           → Daniel's DocuSign User GUID
  fleet-docusign-template-id       → Quote template UUID

Environment variables:
  DOCUSIGN_BASE_URL   → API base, e.g. https://na4.docusign.net/restapi/v2.1
                        (sandbox: https://demo.docusign.net/restapi/v2.1)
  DOCUSIGN_AUTH_BASE  → OAuth base, defaults to account-d.docusign.com (sandbox)
                        Set to account.docusign.com for production
"""
import os
import time
import logging
from typing import Any, Dict, Optional, Tuple

import jwt
import httpx
from google.cloud import secretmanager

logger = logging.getLogger(__name__)

# DocuSign OAuth scope
_DS_OAUTH_SCOPE = "signature impersonation"

# Secret Manager secret names (NAP prefixes with app ID: fleet-sales-agent-)
# RSA key is split into 3 parts (~745 chars each) to work around nap secrets CLI size limit
_SECRET_RSA_KEY_P1 = "fleet-sales-agent-docusign-rsa-key-p1"
_SECRET_RSA_KEY_P2 = "fleet-sales-agent-docusign-rsa-key-p2"
_SECRET_RSA_KEY_P3 = "fleet-sales-agent-docusign-rsa-key-p3"
_SECRET_INTEG_KEY = "fleet-sales-agent-docusign-integration-key"
_SECRET_USER_ID = "fleet-sales-agent-docusign-user-id"
_SECRET_TEMPLATE_ID = "fleet-sales-agent-docusign-template-id"

# Pricing lookup tables
HARDWARE_PRICES: Dict[Tuple[str, str], float] = {
    ("Beam 2 Mini", "128GB"): 159.95,
    ("Beam 2 Mini", "256GB"): 189.95,
    ("Beam 2",      "128GB"): 289.95,
    ("Beam 2",      "256GB"): 299.95,
    ("Nexar One",   "128GB"): 359.95,  # only ships 128GB
}

PLAN_RATES: Dict[str, Tuple[str, float]] = {
    "no-contract": ("Flexible",  25.00),
    "1-year":      ("1 year",    19.99),
    "2-year":      ("2 years",   17.99),
    "3-year":      ("3 years",   14.99),
}

# Maps (camera_model, memory_option) → exact dropdown value in DocuSign template
CAMERA_DROPDOWN: Dict[Tuple[str, str], str] = {
    ("Beam 2",      "128GB"): "Beam2 128GB",
    ("Beam 2",      "256GB"): "Beam2 256 GB",
    ("Beam 2 Mini", "128GB"): "Beam2 mini 128 GB",
    ("Beam 2 Mini", "256GB"): "Beam2 mini 256 GB",
    ("Nexar One",   "128GB"): "Nexar One 128 GB",
    ("Nexar One",   "256GB"): "Nexar One 256 GB",
}


class DocuSignService:
    """Creates DocuSign quote envelopes from a pre-built template."""

    def __init__(self) -> None:
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._account_id: Optional[str] = None
        self._secrets_cache: Dict[str, str] = {}

    # ─── Secret loading ───────────────────────────────────────────────────────

    def _get_secret(self, secret_name: str) -> str:
        """Load a secret from Secret Manager with in-process cache and env var fallback."""
        if secret_name in self._secrets_cache:
            return self._secrets_cache[secret_name]

        try:
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "nexar-corp-systems")
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
            resp = client.access_secret_version(request={"name": name})
            value = resp.payload.data.decode("UTF-8").strip()
            self._secrets_cache[secret_name] = value
            return value
        except Exception as e:
            logger.warning(f"Secret Manager unavailable for {secret_name}: {e}")

        # Env var fallback for local dev (e.g. FLEET_DOCUSIGN_RSA_PRIVATE_KEY)
        env_key = secret_name.upper().replace("-", "_")
        value = os.environ.get(env_key, "")
        if not value:
            raise RuntimeError(
                f"Secret '{secret_name}' not found in Secret Manager or env var '{env_key}'"
            )
        self._secrets_cache[secret_name] = value
        return value

    # ─── Authentication ───────────────────────────────────────────────────────

    def _get_access_token(self) -> str:
        """Return cached access token or fetch a new one via JWT Grant."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        integration_key = self._get_secret(_SECRET_INTEG_KEY)
        user_id = self._get_secret(_SECRET_USER_ID)
        # RSA key stored in 3 parts to work around nap secrets CLI size limit
        import base64 as _b64
        rsa_raw = (self._get_secret(_SECRET_RSA_KEY_P1)
                   + self._get_secret(_SECRET_RSA_KEY_P2)
                   + self._get_secret(_SECRET_RSA_KEY_P3))
        try:
            decoded = _b64.b64decode(rsa_raw).decode("utf-8")
            rsa_private_key = decoded if "BEGIN" in decoded else rsa_raw
        except Exception:
            rsa_private_key = rsa_raw
        logger.info(f"RSA key loaded, len={len(rsa_private_key)}, starts_with_pem={'BEGIN' in rsa_private_key[:50]}")

        auth_base = self._get_auth_base()
        now = int(time.time())
        payload = {
            "iss": integration_key,
            "sub": user_id,
            "aud": auth_base,
            "iat": now,
            "exp": now + 3600,
            "scope": _DS_OAUTH_SCOPE,
        }
        assertion = jwt.encode(payload, rsa_private_key, algorithm="RS256")

        auth_base = self._get_auth_base()
        resp = httpx.post(
            f"https://{auth_base}/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            timeout=15.0,
        )
        if not resp.is_success:
            logger.error(f"DocuSign token error {resp.status_code}: {resp.text}")
            resp.raise_for_status()
        token_data = resp.json()

        self._access_token = token_data["access_token"]
        self._token_expires_at = time.time() + token_data.get("expires_in", 3600)
        logger.info("DocuSign access token refreshed")
        return self._access_token

    def _get_account_id(self) -> str:
        """Return the DocuSign account ID for the authenticated user (cached)."""
        if self._account_id:
            return self._account_id

        token = self._get_access_token()
        auth_base = self._get_auth_base()
        resp = httpx.get(
            f"https://{auth_base}/oauth/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        self._account_id = resp.json()["accounts"][0]["account_id"]
        logger.info(f"DocuSign account ID: {self._account_id}")
        return self._account_id

    def _get_auth_base(self) -> str:
        """OAuth base URL — sandbox by default, override to account.docusign.com for prod."""
        return os.environ.get("DOCUSIGN_AUTH_BASE", "account-d.docusign.com")

    def _get_base_url(self) -> str:
        return os.environ.get(
            "DOCUSIGN_BASE_URL", "https://demo.docusign.net/restapi/v2.1"
        )

    # ─── Pricing computation ──────────────────────────────────────────────────

    def _compute_pricing(self, lead: Any) -> Dict[str, str]:
        """Derive all quote tab values from collected lead fields."""
        camera_model = (lead.camera_model or "").strip()
        memory_option = (lead.memory_option or "128GB").strip()
        subscription = (lead.subscription_plan or "no-contract").strip().lower()
        num_cameras = lead.num_cameras or 1

        # Nexar One only ships in 128GB
        if camera_model == "Nexar One":
            memory_option = "128GB"

        unit_price = HARDWARE_PRICES.get((camera_model, memory_option), 0.0)
        total_hardware = round(unit_price * num_cameras, 2)
        hardware_monthly = round(unit_price / 12, 2)

        plan_name, plan_rate = PLAN_RATES.get(subscription, ("No-Contract", 25.00))
        monthly_total = round(plan_rate * num_cameras, 2)

        first_name = (lead.contact_name or "").split()[0] if lead.contact_name else ""

        # Split phone into country code + local number
        raw_phone = (lead.contact_phone or "").strip()
        if raw_phone.startswith("+"):
            parts = raw_phone.split(" ", 1)
            if len(parts) > 1:
                phone_country_code = parts[0]
                phone_number = parts[1]
            else:
                # No space — try to split known country codes (1, 44, 972, etc.)
                import re as _re
                m = _re.match(r"^(\+\d{1,3})(\d{6,})$", raw_phone)
                if m:
                    phone_country_code = m.group(1)
                    phone_number = m.group(2)
                else:
                    phone_country_code = ""
                    phone_number = raw_phone
        else:
            phone_country_code = "+1"
            phone_number = raw_phone

        camera_dropdown_value = CAMERA_DROPDOWN.get((camera_model, memory_option), camera_model)

        return {
            "first_name":          first_name,
            "business_name":       lead.business_name or "",
            "phone_country_code":  phone_country_code,
            "phone_number":        phone_number,
            "camera_model":      camera_dropdown_value,  # listTab
            "unit_price":        f"${unit_price:,.2f}",
            "hardware_monthly":  f"${hardware_monthly:,.2f}",
            "num_cameras":       str(num_cameras),
            "total_hardware":    f"${total_hardware:,.2f}",
            "initial_term":      plan_name,              # listTab
            "plan_rate":         f"${plan_rate:,.2f}",
            "monthly_total":     f"${monthly_total:,.2f}",
        }

    # ─── Envelope creation ────────────────────────────────────────────────────

    async def create_quote_envelope(
        self,
        lead: Any,
    ) -> str:
        """
        Create a DocuSign envelope from the quote template.
        DocuSign emails the prospect directly — no embedded signing URL.

        Args:
            lead: LeadData instance with all required quote fields populated.

        Returns:
            envelope_id string.

        Raises:
            RuntimeError: on any DocuSign API error.
        """
        token = self._get_access_token()
        account_id = self._get_account_id()
        template_id = self._get_secret(_SECRET_TEMPLATE_ID)
        base_url = self._get_base_url()

        # Log template tab structure so we can verify our labels match
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r_tmpl = await client.get(
                    f"{base_url}/accounts/{account_id}/templates/{template_id}/recipients",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"include_tabs": "true"},
                )
            for signer in r_tmpl.json().get("signers", []):
                for tab_type, tab_list in signer.get("tabs", {}).items():
                    for t in tab_list:
                        logger.info(f"  TEMPLATE {tab_type}: label={t.get('tabLabel')!r} name={t.get('name')!r}")
        except Exception as e:
            logger.warning(f"DocuSign template tab fetch error: {e}")

        pricing = self._compute_pricing(lead)
        camera_model_val = pricing.pop("camera_model")
        initial_term = pricing.pop("initial_term")
        pricing.pop("first_name", None)
        pricing.pop("business_name", None)
        first_name = (lead.contact_name or "").split()[0] if lead.contact_name else ""
        last_name = " ".join((lead.contact_name or "").split()[1:]) if lead.contact_name else ""

        # Create as "sent" — email goes out immediately, then we update tab values via PUT.
        # Signer opens the link after our PUT so they see the pre-filled values.
        envelope_def = {
            "status": "sent",
            "templateId": template_id,
            "templateRoles": [
                {
                    "roleName": "prospect",
                    "name": lead.contact_name or "Fleet Contact",
                    "email": lead.contact_email,
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        logger.info(f"DocuSign envelope_def: {envelope_def}")

        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"{base_url}/accounts/{account_id}/envelopes",
                json=envelope_def,
                headers=headers,
            )

        if r.status_code not in (200, 201):
            raise RuntimeError(
                f"DocuSign envelope creation failed: {r.status_code} — {r.text[:300]}"
            )

        envelope_id = r.json()["envelopeId"]
        logger.info(f"DocuSign envelope created: {envelope_id}")

        # Fetch envelope recipients to get recipientId, then force-set all tab values.
        # templateRoles overrides don't work for company/fullName tab types — PUT tabs directly.
        async with httpx.AsyncClient(timeout=10.0) as client:
            r_recip = await client.get(
                f"{base_url}/accounts/{account_id}/envelopes/{envelope_id}/recipients",
                headers={"Authorization": f"Bearer {token}"},
                params={"include_tabs": "true"},
            )
        try:
            signer = r_recip.json()["signers"][0]
            recipient_id = signer["recipientId"]
            # Build label → (tabId, tabType) map — PUT must use the original tab type
            tab_info_map: Dict[str, tuple] = {}
            for tab_type, tab_list in signer.get("tabs", {}).items():
                for t in tab_list:
                    label = t.get("tabLabel", "")
                    tab_id = t.get("tabId", "")
                    if label and tab_id:
                        tab_info_map[label] = (tab_id, tab_type)
                        logger.info(f"  TAB: type={tab_type} label={label!r} tabId={tab_id!r}")
        except Exception as e:
            logger.warning(f"DocuSign recipients parse error: {e}")
            return envelope_id

        # Map our data values to current template tab labels (updated after template rebuild)
        raw_phone = (lead.contact_phone or "").strip()
        tab_values: Dict[str, str] = {
            # Pricing fields
            "num_cameras":      pricing.get("num_cameras", ""),
            "hardware_monthly": pricing.get("hardware_monthly", ""),
            "total_hardware":   pricing.get("total_hardware", ""),
            "plan_rate":        pricing.get("plan_rate", ""),
            "monthly_total":    pricing.get("monthly_total", ""),
            # Dropdowns
            "camera_model":     camera_model_val,
            "initial_term":     initial_term,
            # Contact fields
            # signer_last_name_text is positioned at "Contact Person" row — needs full name
            # last_name_text is the signature section Last Name box
            "business_name_text":      lead.business_name or "",
            "signer_first_name_text":  first_name,
            "signer_last_name_text":   lead.contact_name or "",
            "last_name_text":          last_name,
            "contact_email_text":      lead.contact_email or "",
            "phone_number_text":       raw_phone,
            "signer_title_text":       "",
        }

        # Build PUT payload grouped by original tab type — DocuSign requires correct type
        put_tabs_by_type: Dict[str, list] = {}
        for label, value in tab_values.items():
            info = tab_info_map.get(label)
            if not info:
                logger.warning(f"DocuSign: no tabId for label {label!r} — skipping")
                continue
            tab_id, tab_type = info
            entry: Dict[str, Any] = {"tabId": tab_id, "tabLabel": label, "value": value}
            if tab_type == "listTabs":
                entry["listSelectedValue"] = value
            else:
                entry["locked"] = True  # boolean (not string)
            put_tabs_by_type.setdefault(tab_type, []).append(entry)

        tabs_payload = {k: v for k, v in put_tabs_by_type.items() if v}
        logger.info(f"DocuSign PUT tabs payload: {tabs_payload}")

        async with httpx.AsyncClient(timeout=15.0) as client:
            r_put = await client.put(
                f"{base_url}/accounts/{account_id}/envelopes/{envelope_id}/recipients/{recipient_id}/tabs",
                json=tabs_payload,
                headers=headers,
            )
        if r_put.is_success:
            logger.info(f"DocuSign PUT tabs OK: {r_put.status_code}")
        else:
            logger.warning(f"DocuSign PUT tabs failed: {r_put.status_code} — {r_put.text[:400]}")

        # Verify values were persisted by DocuSign (not just echoed back)
        async with httpx.AsyncClient(timeout=10.0) as client:
            r_verify = await client.get(
                f"{base_url}/accounts/{account_id}/envelopes/{envelope_id}/recipients",
                headers={"Authorization": f"Bearer {token}"},
                params={"include_tabs": "true"},
            )
        try:
            after_tabs = r_verify.json()["signers"][0].get("tabs", {})
            for tab_type, tab_list in after_tabs.items():
                for t in tab_list:
                    label = t.get("tabLabel", "")
                    value = t.get("value", "")
                    if value:  # only log non-empty
                        logger.info(f"  AFTER: {tab_type} label={label!r} value={value!r}")
        except Exception as e:
            logger.warning(f"DocuSign verify error: {e}")

        return envelope_id
