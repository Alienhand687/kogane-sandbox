import os
import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Union
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from pydantic.fields import FieldInfo

def _arg(val: Any, default: Any = None) -> Any:
    if isinstance(val, FieldInfo):
        return default
    return default if val is None else val

# Dynamic port binding: Render injects PORT; falls back to 8000 locally
PORT = int(os.environ.get("PORT", 8000))
mcp = FastMCP("Kogane-Unified-Sandbox", host="0.0.0.0", port=PORT)

# ============================================================================
# SHARED STATE & SCENARIO FIXTURES
# ============================================================================
STATE_STORE: Dict[str, Dict[str, Any]] = {
    "tenancies": {},
    "vaults": {},
    "inspections": {},
    "covenants": {},
    "audit_trail": []
}

STATIC_FIXTURES: Dict[str, Dict[str, Any]] = {
    "eval_paint_wear": {
        "anomalies": [
            {
                "surface_category": "PAINT_WALL",
                "coordinates_xyz": [2.1, 1.4, 0.0],
                "surface_area_sq_meters": 4.5,
                "volumetric_depth_mm": 0.0,
                "raw_repair_cost_inr": 12000.0,
                "claimed_repair_cost_inr": 18000.0
            }
        ],
        "coverage_pct": 99.2,
        "occlusion": False,
        "drift_pct": 0.8
    },
    "eval_occlusion_trap": {
        "anomalies": [],
        "coverage_pct": 86.4,
        "occlusion": True,
        "occlusion_quadrant": "QUADRANT_2B_FLOOR_OCCLUDED",
        "drift_pct": 1.1
    },
    "eval_tile_damage": {
        "anomalies": [
            {
                "surface_category": "FLOOR_TILE",
                "coordinates_xyz": [1.0, 0.5, -1.2],
                "surface_area_sq_meters": 0.3,
                "volumetric_depth_mm": 6.5,
                "raw_repair_cost_inr": 3500.0,
                "claimed_repair_cost_inr": 9000.0
            }
        ],
        "coverage_pct": 98.8,
        "occlusion": False,
        "drift_pct": 0.5
    }
}

# Merge 100-scenario adversarial evaluation suite into STATIC_FIXTURES
try:
    from eval_fixtures_100 import STATIC_FIXTURES as EVAL_100
    STATIC_FIXTURES.update(EVAL_100)
except ImportError:
    try:
        from sandbox.eval_fixtures_100 import STATIC_FIXTURES as EVAL_100
        STATIC_FIXTURES.update(EVAL_100)
    except ImportError:
        pass


# ============================================================================
# GRANTEX LEAST-PRIVILEGE SCOPE REGISTRY & MOCK VALIDATOR
# ============================================================================
TOOL_GRANTEX_SCOPES: Dict[str, str] = {
    # Agent 1: Escrow & Capital Tools (Pine Labs)
    "create_tripartite_vault": "escrow:vault:create",
    "trigger_treps_sweep": "escrow:repo:invest",
    "lock_dispute_subvault": "escrow:dispute:lock",
    "execute_split_payout": "escrow:payout:execute",
    "invoke_fldg_deduction": "escrow:fldg:deduct",
    # Agent 2: Condition Arbitration Tools (Delhivery / CPWD / SOR)
    "dispatch_delhivery_rvp": "condition:rvp:dispatch",
    "ingest_mesh_baseline": "condition:baseline:ingest",
    "compute_pointcloud_delta": "condition:delta:compute",
    "apply_cpwd_depreciation": "condition:cpwd:depreciate",
    "query_sor_ceiling": "condition:sor:query",
    # Agent 3: Covenant & Legal Tools (Gnani / WhatsApp)
    "transcribe_gnani_asr": "covenant:asr:transcribe",
    "strip_sentiment_bias": "covenant:sentiment:strip",
    "generate_it_act_addendum": "covenant:addendum:generate",
    "dispatch_whatsapp_hsm": "covenant:hsm:dispatch",
    # Platform Audit
    "append_google_sheet_row": "audit:ledger:append"
}

def verify_grantex_authorization(tool_name: str, auth_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Validates Grantex least-privilege authorization against the required tool scope.
    In permissive dev mode (auth_token is None/empty), access is granted with a mock audit trail.
    If auth_token is provided, the required scope or admin scope must be present.
    """
    required_scope = TOOL_GRANTEX_SCOPES.get(tool_name, "general:access")
    if not isinstance(auth_token, str) or not auth_token.strip():
        return {
            "authorized": True,
            "mode": "PERMISSIVE_DEV_MOCK",
            "scope_checked": required_scope,
            "status": "PASS"
        }
    
    token_str = auth_token.strip()
    if required_scope in token_str or "admin:all" in token_str or "grantex:superadmin" in token_str:
        return {
            "authorized": True,
            "mode": "STRICT_TOKEN_VERIFIED",
            "scope_checked": required_scope,
            "status": "PASS"
        }
    
    return {
        "authorized": False,
        "mode": "TOKEN_REJECTED",
        "scope_checked": required_scope,
        "error": f"GRANTEX_ACCESS_DENIED: Token lacks required scope '{required_scope}'"
    }

# ============================================================================
# AGENT 1: ESCROW & CAPITAL TOOLS (PINE LABS / RBI ESCROW)
# ============================================================================

@mcp.tool(
    name="create_tripartite_vault",
    description="Simulates opening an RBI-regulated tripartite custody account via Pine Labs and an Independent Corporate Trustee."
)
async def create_tripartite_vault(
    tenancy_id: str = Field(description="Unique lease UUID"),
    tenant_id: str = Field(description="Tenant UUID or PAN"),
    landlord_id: str = Field(description="Landlord UUID or PAN"),
    deposit_amount_inr: float = Field(description="Total refundable security deposit locked"),
    tenancy_period_months: Optional[int] = Field(default=None, description="Lease duration in months"),
    lease_duration_months: Optional[int] = Field(default=None, description="Lease duration in months (canonical spec alias)"),
    trustee_code: Optional[str] = Field(default="AXIS_TRUSTEE", description="Designated independent trustee (e.g. AXIS_TRUSTEE, ORBIS, VISTRA)"),
    custody_bank: Optional[str] = Field(default="ICICI", description="Custody bank (e.g. ICICI, AXIS)"),
    idempotency_key: Optional[str] = Field(default=None, description="Unique idempotency key"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    tenancy_id = _arg(tenancy_id)
    tenant_id = _arg(tenant_id)
    landlord_id = _arg(landlord_id)
    deposit_amount_inr = _arg(deposit_amount_inr, 0.0)
    tenancy_period_months = _arg(tenancy_period_months)
    lease_duration_months = _arg(lease_duration_months)
    trustee_code = _arg(trustee_code, "AXIS_TRUSTEE")
    custody_bank = _arg(custody_bank, "ICICI")
    idempotency_key = _arg(idempotency_key)
    grantex_token = _arg(grantex_token)

    auth = verify_grantex_authorization("create_tripartite_vault", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    if deposit_amount_inr > 1000000.0:
        return json.dumps({
            "status": "DEPOSIT_LIMIT_EXCEEDED",
            "error": "DEPOSIT_LIMIT_EXCEEDED: Security deposit exceeds Rs 10,00,000 ceiling. Requires multi-sig KYC approval."
        })
    duration = lease_duration_months if lease_duration_months is not None else (tenancy_period_months if tenancy_period_months is not None else 11)
    vault_id = f"VAULT_{tenancy_id.upper()[:8]}_{int(deposit_amount_inr)}"
    record = {
        "vault_id": vault_id,
        "tenancy_id": tenancy_id,
        "tenant_id": tenant_id,
        "landlord_id": landlord_id,
        "total_deposit_inr": deposit_amount_inr,
        "undisputed_balance_inr": deposit_amount_inr,
        "disputed_subvault_inr": 0.0,
        "latent_defect_bond_inr": 0.0,
        "accrued_yield_inr": 0.0,
        "trustee_code": trustee_code or "AXIS_TRUSTEE",
        "custody_bank": custody_bank or "ICICI",
        "lease_duration_months": duration,
        "tenancy_period_months": duration,
        "status": "VAULT_INITIALIZED",
        "created_at_utc": datetime.now(timezone.utc).isoformat()
    }
    STATE_STORE["vaults"][vault_id] = record
    STATE_STORE["tenancies"][tenancy_id] = {"vault_id": vault_id, "status": "ACTIVE_TENANCY"}
    return json.dumps(record)

@mcp.tool(
    name="trigger_treps_sweep",
    description="Simulates daily CCIL Tri-Party Repo (TREPS) sovereign overnight sweeps (yielding 6.5%-7.0% p.a.)."
)
async def trigger_treps_sweep(
    vault_id: str = Field(description="Tripartite Escrow Vault identifier"),
    sweep_amount_inr: Optional[float] = Field(default=None, description="Float balance to deploy into overnight sovereign repos"),
    amount_inr: Optional[float] = Field(default=None, description="Float balance to deploy (canonical spec alias)"),
    sweep_type: Optional[str] = Field(default="SWEEP_IN", description="Sweep direction: SWEEP_IN or SWEEP_OUT"),
    annualized_yield_pct: float = Field(default=6.75, description="Benchmark yield rate"),
    market_cutoff_override: Optional[bool] = Field(default=False, description="Enforces RBI/CCIL market settlement windows"),
    idempotency_key: Optional[str] = Field(default=None, description="Unique idempotency key"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    vault_id = _arg(vault_id)
    sweep_amount_inr = _arg(sweep_amount_inr)
    amount_inr = _arg(amount_inr)
    sweep_type = _arg(sweep_type, "SWEEP_IN")
    annualized_yield_pct = _arg(annualized_yield_pct, 6.75)
    market_cutoff_override = _arg(market_cutoff_override, False)
    idempotency_key = _arg(idempotency_key)
    grantex_token = _arg(grantex_token)

    auth = verify_grantex_authorization("trigger_treps_sweep", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    effective_amount = amount_inr if amount_inr is not None else (sweep_amount_inr if sweep_amount_inr is not None else 0.0)
    daily_yield = round(effective_amount * (annualized_yield_pct / 100.0) / 365.0, 2)
    landlord_share = round(daily_yield * 0.5, 2)
    platform_share = round(daily_yield - landlord_share, 2)

    if vault_id in STATE_STORE["vaults"]:
        STATE_STORE["vaults"][vault_id]["accrued_yield_inr"] += daily_yield

    return json.dumps({
        "status": "SWEEP_EXECUTED",
        "vault_id": vault_id,
        "swept_amount_inr": effective_amount,
        "sweep_type": sweep_type or "SWEEP_IN",
        "daily_yield_accrued_inr": daily_yield,
        "landlord_credit_inr": landlord_share,
        "platform_maintenance_inr": platform_share,
        "repo_instrument": "CCIL_TREPS_OVERNIGHT_SOVEREIGN"
    })

@mcp.tool(
    name="lock_dispute_subvault",
    description="Partitions contested damage deltas into an escrow freeze sub-vault while leaving the undisputed balance liquid."
)
async def lock_dispute_subvault(
    vault_id: Optional[str] = Field(default=None, description="Tripartite Escrow Vault ID"),
    master_vault_id: Optional[str] = Field(default=None, description="Master vault ID (canonical spec alias)"),
    disputed_amount_inr: Optional[float] = Field(default=None, description="Contested damage delta to be quarantined"),
    contested_amount_inr: Optional[float] = Field(default=None, description="Contested damage delta (canonical spec alias)"),
    dispute_reason: Optional[str] = Field(default=None, description="Grounds for contestation"),
    claim_reason: Optional[str] = Field(default=None, description="Grounds for contestation (canonical spec alias)"),
    odr_institution: Optional[str] = Field(default="SAMA", description="ODR arbitration institution: SAMA or PRESOLV360"),
    idempotency_key: Optional[str] = Field(default=None, description="Unique idempotency key"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    vault_id = _arg(vault_id)
    master_vault_id = _arg(master_vault_id)
    disputed_amount_inr = _arg(disputed_amount_inr)
    contested_amount_inr = _arg(contested_amount_inr)
    dispute_reason = _arg(dispute_reason)
    claim_reason = _arg(claim_reason)
    odr_institution = _arg(odr_institution, "SAMA")
    idempotency_key = _arg(idempotency_key)
    grantex_token = _arg(grantex_token)

    auth = verify_grantex_authorization("lock_dispute_subvault", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    target_vault_id = master_vault_id or vault_id or "VAULT_UNKNOWN"
    effective_amount = contested_amount_inr if contested_amount_inr is not None else (disputed_amount_inr if disputed_amount_inr is not None else 0.0)
    effective_reason = claim_reason or dispute_reason or "UNSPECIFIED_DISPUTE"

    vault = STATE_STORE["vaults"].get(target_vault_id, {
        "undisputed_balance_inr": 150000.0,
        "disputed_subvault_inr": 0.0
    })

    if effective_amount > vault["undisputed_balance_inr"]:
        effective_amount = vault["undisputed_balance_inr"]

    vault["undisputed_balance_inr"] -= effective_amount
    vault["disputed_subvault_inr"] += effective_amount
    subvault_id = f"SUBVAULT_DISPUTE_{hashlib.md5(effective_reason.encode()).hexdigest()[:8]}"

    return json.dumps({
        "status": "SUBVAULT_PARTITIONED",
        "subvault_id": subvault_id,
        "master_vault_id": target_vault_id,
        "quarantined_amount_inr": effective_amount,
        "isolated_amount_inr": effective_amount,
        "remaining_liquid_inr": vault["undisputed_balance_inr"],
        "liquid_releasable_balance_inr": vault["undisputed_balance_inr"],
        "odr_escalation_eligible": True,
        "odr_institution": odr_institution or "SAMA",
        "odr_docket_number": f"ODR-{subvault_id}"
    })

@mcp.tool(
    name="execute_split_payout",
    description="Executes instant H2H IMPS/UPI dual-party disbursement once T-0 QR cryptographic verification clears."
)
async def execute_split_payout(
    vault_id: str = Field(description="Tripartite Escrow Vault ID"),
    tenant_payout_inr: Optional[float] = Field(default=None, description="Liquid release sanctioned to tenant"),
    undisputed_tenant_inr: Optional[float] = Field(default=None, description="Undisputed tenant release (canonical spec alias)"),
    landlord_payout_inr: Optional[float] = Field(default=None, description="Approved deduction balance paid to landlord"),
    landlord_deduction_inr: Optional[float] = Field(default=None, description="Approved deduction balance paid to landlord (canonical spec alias)"),
    latent_defect_hold_pct: Optional[float] = Field(default=15.0, description="Float percentage reserved for 7-day Latent Defect Bond"),
    latent_bond_float_inr: Optional[float] = Field(default=None, description="Explicit rupee float for 7-day Latent Defect Bond"),
    t0_qr_nonce: Optional[str] = Field(default=None, description="Cryptographic nonce verified at key-exchange"),
    possession_qr_signature: Optional[str] = Field(default=None, description="Cryptographic signature from T-0 scan (canonical spec alias)"),
    tenant_payout_target: Optional[Union[Dict[str, Any], str]] = Field(default=None, description="Tenant payout destination account / UPI"),
    landlord_payout_target: Optional[Union[Dict[str, Any], str]] = Field(default=None, description="Landlord payout destination account / UPI"),
    idempotency_key: Optional[str] = Field(default=None, description="Unique idempotency key"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    vault_id = _arg(vault_id)
    tenant_payout_inr = _arg(tenant_payout_inr)
    undisputed_tenant_inr = _arg(undisputed_tenant_inr)
    landlord_payout_inr = _arg(landlord_payout_inr)
    landlord_deduction_inr = _arg(landlord_deduction_inr)
    latent_defect_hold_pct = _arg(latent_defect_hold_pct, 15.0)
    latent_bond_float_inr = _arg(latent_bond_float_inr)
    t0_qr_nonce = _arg(t0_qr_nonce)
    possession_qr_signature = _arg(possession_qr_signature)
    tenant_payout_target = _arg(tenant_payout_target)
    landlord_payout_target = _arg(landlord_payout_target)
    idempotency_key = _arg(idempotency_key)
    grantex_token = _arg(grantex_token)

    auth = verify_grantex_authorization("execute_split_payout", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    nonce = (possession_qr_signature or t0_qr_nonce or "").strip()
    is_valid_nonce = (
        nonce.startswith("NONCE_T0_VALID")
        or nonce.startswith("SIG-QR-T0")
        or "AUTHENTICATED" in nonce.upper()
        or nonce == "UNILATERAL_EXIT_TIMER_EXPIRED"
    )
    if not is_valid_nonce:
        return json.dumps({
            "status": "PAYOUT_REJECTED",
            "error": "INVALID_POSSESSION_NONCE: Move-out handover QR was not scanned or is counterfeit."
        })

    effective_tenant_payout = undisputed_tenant_inr if undisputed_tenant_inr is not None else (tenant_payout_inr if tenant_payout_inr is not None else 0.0)
    effective_landlord_payout = landlord_deduction_inr if landlord_deduction_inr is not None else (landlord_payout_inr if landlord_payout_inr is not None else 0.0)

    if latent_bond_float_inr is not None:
        bond_hold = round(float(latent_bond_float_inr), 2)
        immediate_tenant_release = round(effective_tenant_payout, 2)
    else:
        hold_pct = latent_defect_hold_pct if latent_defect_hold_pct is not None else 15.0
        bond_hold = round(effective_tenant_payout * (hold_pct / 100.0), 2)
        immediate_tenant_release = round(effective_tenant_payout - bond_hold, 2)

    return json.dumps({
        "status": "SETTLED_TERMINATED",
        "vault_id": vault_id,
        "tenant_settlement_utr": f"PINE_IMPS_{int(datetime.now().timestamp())}_01",
        "tenant_immediate_utr": f"PINE_IMPS_{int(datetime.now().timestamp())}_01",
        "tenant_immediate_payout_inr": immediate_tenant_release,
        "undisputed_tenant_inr": immediate_tenant_release,
        "latent_defect_bond_hold_inr": bond_hold,
        "latent_bond_float_inr": bond_hold,
        "latent_subvault_id": f"SUBVAULT_BOND_{vault_id[:8]}",
        "landlord_settlement_utr": f"PINE_IMPS_{int(datetime.now().timestamp())}_02" if effective_landlord_payout > 0 else "N/A",
        "landlord_utr": f"PINE_IMPS_{int(datetime.now().timestamp())}_02" if effective_landlord_payout > 0 else "N/A",
        "landlord_payout_inr": effective_landlord_payout,
        "landlord_deduction_inr": effective_landlord_payout,
        "bond_release_timer_utc": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    })

@mcp.tool(
    name="invoke_fldg_deduction",
    description="Liquidates security deposit float directly to the partner NBFC when monthly e-NACH rent debit bounces."
)
async def invoke_fldg_deduction(
    vault_id: str = Field(description="Tripartite Escrow Vault ID"),
    missed_rent_amount_inr: Optional[float] = Field(default=None, description="Contractual monthly rent due"),
    rent_arrears_inr: Optional[float] = Field(default=None, description="Contractual monthly rent due (canonical spec alias)"),
    enach_bounce_code: Optional[str] = Field(default="INSUFFICIENT_FUNDS", description="NPCI failure code (e.g., 'INSUFFICIENT_FUNDS')"),
    grace_period_expired: Optional[bool] = Field(default=True, description="True if 72-hour grace timer elapsed"),
    nbfc_partner_id: Optional[str] = Field(default=None, description="NBFC lending partner ID"),
    default_month_cycle: Optional[int] = Field(default=None, description="Defaulted month index"),
    mandate_failure_evidence: Optional[Union[Dict[str, Any], str]] = Field(default=None, description="Structured failure evidence (e.g. UMRN, bounce reason, grace expiry)"),
    idempotency_key: Optional[str] = Field(default=None, description="Unique idempotency key"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    vault_id = _arg(vault_id)
    missed_rent_amount_inr = _arg(missed_rent_amount_inr)
    rent_arrears_inr = _arg(rent_arrears_inr)
    enach_bounce_code = _arg(enach_bounce_code, "INSUFFICIENT_FUNDS")
    grace_period_expired = _arg(grace_period_expired, True)
    nbfc_partner_id = _arg(nbfc_partner_id)
    default_month_cycle = _arg(default_month_cycle)
    mandate_failure_evidence = _arg(mandate_failure_evidence)
    idempotency_key = _arg(idempotency_key)
    grantex_token = _arg(grantex_token)

    auth = verify_grantex_authorization("invoke_fldg_deduction", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    effective_rent = rent_arrears_inr if rent_arrears_inr is not None else (missed_rent_amount_inr if missed_rent_amount_inr is not None else 0.0)
    effective_bounce_code = enach_bounce_code or "INSUFFICIENT_FUNDS"

    if isinstance(mandate_failure_evidence, dict):
        effective_bounce_code = mandate_failure_evidence.get("bounce_reason_code", effective_bounce_code)

    if grace_period_expired is False:
        return json.dumps({
            "status": "FLDG_REJECTED",
            "error": "GRACE_PERIOD_ACTIVE: Cannot liquidate collateral before the 72-hour settlement window lapses."
        })

    return json.dumps({
        "status": "FACTORING_REIMBURSED",
        "vault_id": vault_id,
        "nbfc_settlement_utr": f"NBFC_REIMBURSE_{hashlib.sha256(vault_id.encode()).hexdigest()[:10]}",
        "recovered_amount_inr": effective_rent,
        "liquidated_amount_inr": effective_rent,
        "enach_bounce_code": effective_bounce_code,
        "covenant_state": "COLLATERAL_DEGRADED",
        "collateral_depleted_alert": True
    })

# ============================================================================
# AGENT 2: CONDITION ARBITRATION TOOLS (DELHIVERY / PREIMAGE / CPWD / SOR)
# ============================================================================

@mcp.tool(
    name="dispatch_delhivery_rvp",
    description="Dispatches a simulated Delhivery Reverse Logistics Quality Check (QC-RVP) gig worker as an indifferent sensor rig."
)
async def dispatch_delhivery_rvp(
    tenancy_id: str = Field(description="Unique lease UUID"),
    pincode: str = Field(description="6-digit Indian Postal PIN code"),
    latitude: float = Field(description="Property latitude"),
    longitude: float = Field(description="Property longitude"),
    inspection_type: str = Field(default="MOVE_OUT_AUDIT", description="'MOVE_OUT_AUDIT' or 'SUPERVISORY_RESCAN'"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    auth = verify_grantex_authorization("dispatch_delhivery_rvp", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    
    if inspection_type not in ["MOVE_OUT_AUDIT", "SUPERVISORY_RESCAN"]:
        return json.dumps({
            "status": "INVALID_INSPECTION_TYPE",
            "error": f"INVALID_INSPECTION_TYPE: '{inspection_type}' is not supported. Must be 'MOVE_OUT_AUDIT' or 'SUPERVISORY_RESCAN'."
        })

    if pincode == "000000":
        return json.dumps({"status": "SERVICEABILITY_DEFICIT", "error": "PIN code not serviceable by primary fleet."})

    if not (isinstance(pincode, str) and pincode.isdigit() and len(pincode) == 6):
        return json.dumps({
            "status": "INVALID_PINCODE",
            "error": f"INVALID_PINCODE: '{pincode}' must be a 6-digit postal PIN code."
        })

    cache_key = f"dispatch_{tenancy_id}_{inspection_type}"
    inspections = STATE_STORE.setdefault("inspections", {})
    if cache_key in inspections:
        cached = inspections[cache_key]
        return json.dumps({
            "status": "ALREADY_DISPATCHED",
            "waybill": cached["waybill"],
            "assigned_agent_id": cached["assigned_agent_id"],
            "eta": cached["eta"],
            "inspection_protocol": cached["inspection_protocol"]
        })

    hex_part = hashlib.sha256(f"{tenancy_id}_{inspection_type}_{pincode}".encode()).hexdigest()[:8].upper()
    waybill = f"DEL_RVP_{pincode}_{hex_part}"
    record = {
        "waybill": waybill,
        "assigned_agent_id": "DEL_AGENT_BLR_404",
        "eta": "25 mins (Simulated)",
        "inspection_protocol": "BLIND_AR_SLAM_SWEEP"
    }
    inspections[cache_key] = record

    return json.dumps({
        "status": "DISPATCHED",
        "waybill": waybill,
        "assigned_agent_id": record["assigned_agent_id"],
        "eta": record["eta"],
        "inspection_protocol": record["inspection_protocol"]
    })

@mcp.tool(
    name="ingest_mesh_baseline",
    description="Validates WebAR move-in spatial baseline coverage (must be >= 98.0%) and locks the SHA-256 hash."
)
async def ingest_mesh_baseline(
    tenancy_id: str = Field(description="Unique lease UUID"),
    video_stream_s3_uri: str = Field(description="S3 bucket path to video sweep"),
    imu_spatial_data_s3_uri: str = Field(description="S3 bucket path to IMU sensors"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    auth = verify_grantex_authorization("ingest_mesh_baseline", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    mock_hash = hashlib.sha256(f"{tenancy_id}_baseline_raw".encode()).hexdigest()
    STATE_STORE["inspections"][f"{tenancy_id}_baseline"] = {
        "hash": mock_hash,
        "coverage_pct": 99.4,
        "status": "LOCKED"
    }
    return json.dumps({
        "status": "BASELINE_LOCKED",
        "tenancy_id": tenancy_id,
        "mesh_id": f"mesh_baseline_{tenancy_id[:8]}",
        "surface_coverage_pct": 99.4,
        "mesh_sha256_hash": mock_hash
    })

@mcp.tool(
    name="compute_pointcloud_delta",
    description="Computes rigid ICP alignment and point-cloud mesh subtraction (Delta C = Exit - Baseline)."
)
async def compute_pointcloud_delta(
    tenancy_id: str = Field(description="Unique lease UUID or static scenario name"),
    baseline_mesh_id: str = Field(description="Baseline mesh reference ID"),
    exit_mesh_id: str = Field(description="Exit mesh reference ID"),
    tolerance_threshold_mm: float = Field(default=3.0),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    auth = verify_grantex_authorization("compute_pointcloud_delta", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    fixture = STATIC_FIXTURES.get(tenancy_id, STATIC_FIXTURES["eval_paint_wear"])

    if fixture.get("occlusion"):
        return json.dumps({
            "status": "OCCLUSION_DETECTED",
            "coverage_pct": fixture["coverage_pct"],
            "flagged_quadrant": fixture.get("occlusion_quadrant"),
            "error": "Volumetric obstruction detected. Re-inspection required."
        })

    return json.dumps({
        "status": "DELTA_COMPUTED",
        "tenancy_id": tenancy_id,
        "coverage_pct": fixture.get("coverage_pct", 99.5),
        "gross_discrepancies_found": len(fixture["anomalies"]),
        "anomalies": fixture["anomalies"],
        "mesh_drift_pct": fixture["drift_pct"]
    })

@mcp.tool(
    name="apply_cpwd_depreciation",
    description="Applies statutory Central Public Works Department (CPWD) straight-line depreciation schedules to detected anomalies."
)
async def apply_cpwd_depreciation(
    tenancy_id: str = Field(description="Unique lease UUID"),
    tenancy_duration_months: int = Field(description="Total months elapsed in tenancy"),
    raw_anomalies: str = Field(description="JSON array of anomalies or string representation"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    auth = verify_grantex_authorization("apply_cpwd_depreciation", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    
    try:
        anomalies_list = json.loads(raw_anomalies) if isinstance(raw_anomalies, str) else raw_anomalies
        if not isinstance(anomalies_list, list):
            return json.dumps({"status": "MALFORMED_JSON_PAYLOAD", "error": "raw_anomalies must be a JSON array"})
    except Exception:
        return json.dumps({"status": "MALFORMED_JSON_PAYLOAD", "error": "Malformed JSON payload in raw_anomalies"})

    cpwd_lifespans = {
        "PAINT_WALL": 24, "PAINTING": 24, "PAINT": 24,
        "FLOOR_TILE": 120, "FLOORING": 120, "TILE": 120,
        "FIXTURE_PLUMBING": 60, "PLUMBING_FIXTURE": 60, "PLUMBING": 60, "SANITARY_PLUMBING": 60,
        "FIXTURE_ELECTRICAL": 60, "ELECTRICAL_FITTING": 60, "ELECTRICAL": 60, "ELECTRICAL_FIXTURES": 60,
        "CARPENTRY_DOOR": 60, "DOOR_WOOD": 60, "WOODEN_DOOR": 60, "CARPENTRY": 60
    }
    default_sor_caps = {
        "PAINT_WALL": 3000.0, "PAINTING": 3000.0, "PAINT": 3000.0,
        "FLOOR_TILE": 4000.0, "FLOORING": 4000.0, "TILE": 4000.0,
        "FIXTURE_PLUMBING": 800.0, "PLUMBING_FIXTURE": 800.0, "PLUMBING": 800.0, "SANITARY_PLUMBING": 800.0,
        "FIXTURE_ELECTRICAL": 1100.0, "ELECTRICAL_FITTING": 1100.0, "ELECTRICAL": 1100.0, "ELECTRICAL_FIXTURES": 1100.0,
        "CARPENTRY_DOOR": 2000.0, "DOOR_WOOD": 2000.0, "WOODEN_DOOR": 2000.0, "CARPENTRY": 2000.0
    }
    results = []

    for item in anomalies_list:
        if not isinstance(item, dict):
            return json.dumps({"status": "INVALID_ANOMALY_PAYLOAD", "error": "Item in raw_anomalies must be an object"})

        cat = item.get("surface_category")
        if not cat or cat not in cpwd_lifespans:
            return json.dumps({
                "status": "UNRECOGNIZED_SURFACE_CATEGORY",
                "error": f"UNRECOGNIZED_SURFACE_CATEGORY: Surface category '{cat}' is not in statutory CPWD schedule."
            })
        lifespan = cpwd_lifespans[cat]

        if "raw_repair_cost_inr" not in item:
            return json.dumps({
                "status": "INVALID_ANOMALY_PAYLOAD",
                "error": "INVALID_ANOMALY_PAYLOAD: Missing required field 'raw_repair_cost_inr'."
            })

        raw_cost = item["raw_repair_cost_inr"]
        if raw_cost is None or not isinstance(raw_cost, (int, float)) or raw_cost < 0.0:
            return json.dumps({
                "status": "INVALID_ANOMALY_PAYLOAD",
                "error": f"INVALID_ANOMALY_PAYLOAD: Invalid raw_repair_cost_inr '{raw_cost}'."
            })
        raw_cost = float(raw_cost)

        # Cap-then-depreciate: clamp base cost to SOR cap if explicitly provided
        if "sor_ceiling_cap_inr" in item and item["sor_ceiling_cap_inr"] is not None:
            sor_cap = float(item["sor_ceiling_cap_inr"])
            clamped_base = min(raw_cost, sor_cap)
        else:
            sor_cap = raw_cost
            clamped_base = raw_cost

        # Exclusions: statutory lifespan exceeded, pre-existing defect, or sub-noise floor (<3mm)
        is_pre_existing = item.get("is_pre_existing", False)
        depth_mm = float(item.get("volumetric_depth_mm", item.get("depth_mm", 10.0)))
        
        if tenancy_duration_months >= lifespan:
            factor = 0.0
            rationale = f"CPWD statutory lifespan ({lifespan}m) exceeded. Classified as 100% normal wear-and-tear."
        elif is_pre_existing:
            factor = 0.0
            rationale = "Pre-existing defect verified in move-in baseline mesh. Tenant liability is INR 0.00."
        elif depth_mm < 3.0:
            factor = 0.0
            rationale = f"Volumetric depth ({depth_mm}mm) below statutory measurement noise floor (3.0mm). Tenant liability is INR 0.00."
        else:
            factor = max(0.0, 1.0 - (tenancy_duration_months / lifespan))
            rationale = f"Depreciated via CPWD schedule ({tenancy_duration_months}/{lifespan} months consumed)."

        allowable = round(clamped_base * factor, 2)
        results.append({
            "surface_category": cat,
            "raw_cost_inr": raw_cost,
            "sor_ceiling_cap_inr": sor_cap,
            "clamped_base_cost_inr": clamped_base,
            "depreciation_factor": round(factor, 4),
            "allowable_deduction_inr": allowable,
            "statutory_rationale": rationale
        })

    total_sanctioned = round(sum(r["allowable_deduction_inr"] for r in results), 2)
    return json.dumps({
        "status": "DEPRECIATION_APPLIED",
        "tenancy_id": tenancy_id,
        "total_sanctioned_deduction_inr": total_sanctioned,
        "evaluated_deductions": results
    })

@mcp.tool(
    name="query_sor_ceiling",
    description="Queries hyper-local Schedule of Rates (SOR) pegged to Urban Company rate cards to establish absolute cost caps."
)
async def query_sor_ceiling(
    pincode: str = Field(description="6-digit Indian Postal PIN code"),
    trade_category: str = Field(description="Trade: PAINTING, PLUMBING, ELECTRICAL, CARPENTRY, or FLOORING"),
    repair_item_code: str = Field(description="Standardized repair fixture identifier"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    auth = verify_grantex_authorization("query_sor_ceiling", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    rate_table = {
        "PAINTING": {"labor": 1200.0, "material": 1800.0, "total": 3000.0},
        "FLOORING": {"labor": 1500.0, "material": 2500.0, "total": 4000.0},
        "PLUMBING": {"labor": 450.0, "material": 350.0, "total": 800.0},
        "ELECTRICAL": {"labor": 500.0, "material": 600.0, "total": 1100.0},
        "CARPENTRY": {"labor": 1000.0, "material": 1500.0, "total": 2500.0}
    }
    trade_upper = trade_category.upper()
    if trade_upper not in rate_table:
        return json.dumps({
            "status": "SOR_CATEGORY_NOT_FOUND",
            "error": f"SOR_CATEGORY_NOT_FOUND: Trade category '{trade_category}' not recognized in Urban Company SOR."
        })
    caps = rate_table[trade_upper]
    return json.dumps({
        "pincode": pincode,
        "trade_category": trade_category,
        "max_allowable_labor_inr": caps["labor"],
        "max_allowable_material_inr": caps["material"],
        "total_ceiling_cap_inr": caps["total"],
        "rate_source": "URBAN_COMPANY_SOR_V4_REST_API"
    })

# ============================================================================
# AGENT 3: COVENANT & LEGAL TOOLS (GNANI / IT ACT / WHATSAPP HSM)
# ============================================================================

@mcp.tool(
    name="transcribe_gnani_asr",
    description="Transcribes vernacular audio via Gnani, generates Section 63 BSA SHA-256 evidence hash, and normalizes text to English."
)
async def transcribe_gnani_asr(
    tenancy_id: str = Field(description="Unique lease UUID"),
    raw_audio_s3_uri: str = Field(description="S3 bucket URI of recorded audio file"),
    source_language_hint: str = Field(default="hi-IN", description="Language code: hi-IN, kn-IN, ta-IN, te-IN, en-IN")
) -> str:
    # 1. Deterministic failure / noise trigger (for testing CV1 & edge case 10.1)
    if "unintelligible" in raw_audio_s3_uri or "noise" in raw_audio_s3_uri:
        return json.dumps({
            "status": "AUDIO_INTELLIGIBILITY_FAILED",
            "tenancy_id": tenancy_id,
            "acoustic_confidence_score": 0.45,
            "error": "Acoustic confidence below statutory threshold (0.65). Ambient noise too high."
        })

    # 2. Unsupported language trigger (edge case 10.4)
    if source_language_hint not in ["hi-IN", "kn-IN", "ta-IN", "te-IN", "en-IN"]:
        return json.dumps({
            "status": "UNSUPPORTED_LANGUAGE",
            "tenancy_id": tenancy_id,
            "acoustic_confidence_score": 0.0,
            "error": f"Dialect {source_language_hint} is not supported by current Gnani acoustic model."
        })

    # 3. Cryptographic digest anchoring for Section 63 BSA 2023 admissibility
    mock_hash = hashlib.sha256(raw_audio_s3_uri.encode()).hexdigest()

    # Pre-baked vernacular speech fixtures
    transcripts = {
        "hi-IN": (
            "Dekho bhaiya, geyser pichle teen din se kharab hai. Agar Friday tak theek nahi karwaya toh rent se kaat lunga main seedha.",
            "The geyser has been broken for three days. If not repaired by Friday, I will deduct it directly from the rent."
        ),
        "kn-IN": (
            "Nodi sir, geyser repair agilla. Friday olage sari madlilla andre nanu rent deduct madtini.",
            "The geyser is not repaired. If not fixed by Friday, I will deduct it directly from rent."
        ),
        "en-IN": (
            "The geyser has been leaking for three days. If you do not fix it by Friday, I will deduct it from next month's rent.",
            "The geyser has been leaking for three days. If you do not fix it by Friday, I will deduct it from next month's rent."
        )
    }
    raw_text, norm_text = transcripts.get(source_language_hint, transcripts["hi-IN"])

    return json.dumps({
        "status": "TRANSCRIBED_AND_HASHED",
        "tenancy_id": tenancy_id,
        "audio_sha256_hash": mock_hash,
        "source_language_detected": source_language_hint,
        "original_transcript": raw_text,
        "normalized_english_text": norm_text,
        "acoustic_confidence_score": 0.94,
        "duration_seconds": 12.4,
        "statutory_compliance": "Bharatiya Sakshya Adhiniyam, 2023 (Section 63)"
    })

@mcp.tool(
    name="strip_sentiment_bias",
    description="Strips hostility and threats, normalizes text, and extracts legal covenant parameters."
)
async def strip_sentiment_bias(
    tenancy_id: str = "TEN-COV-001",
    raw_message_text: str = "",
    raw_transcript: str = "",
    sender_role: str = "TENANT",
    evidence_hash: str = "MOCK_HASH_DIGEST"
) -> str:
    # LLM jo bhi argument pass kare, text pick karo
    text = (raw_message_text or raw_transcript or "").strip()
    lower_text = text.lower()
    tid = tenancy_id if tenancy_id else "TEN-COV-001"

    # 1. Threat & Hostility Detection
    threat_patterns = [
        r"not paying rent", r"rent se kaat", r"rent deduct", r"nahi dunga",
        r"withhold.*rent", r"smash", r"thief", r"insane", r"useless", r"idiot"
    ]
    is_hostile = any(re.search(p, lower_text) for p in threat_patterns) or "insane" in lower_text

    # 2. Dynamic Fixture Parsing
    target_fixture = None
    if "geyser" in lower_text:
        target_fixture = "BATHROOM_GEYSER"
    elif "ac" in lower_text:
        target_fixture = "AIR_CONDITIONER"
    elif "tap" in lower_text:
        target_fixture = "BATHROOM_TAP"
    elif "fan" in lower_text:
        target_fixture = "CEILING_FAN"

    # 3. Dynamic Date Parsing
    agreed_deadline_iso = None
    if any(k in lower_text for k in ["6 october 2026", "2026-10-06", "october 6"]):
        agreed_deadline_iso = "2026-10-06"
    elif any(k in lower_text for k in ["8 october 2026", "2026-10-08"]):
        agreed_deadline_iso = "2026-10-08"

    # 4. Dynamic Cost Bearer Parsing
    cost_bearer = "UNRESOLVED"
    if any(k in lower_text for k in ["landlord will pay", "landlord ka kharcha", "landlord pay", "owner will pay"]):
        cost_bearer = "LANDLORD"
    elif any(k in lower_text for k in ["tenant will pay", "i will pay", "main dunga"]):
        cost_bearer = "TENANT"

    # CV4 Gate: Fixture, Date, and Cost Bearer sab honge tabhi True hoga
    covenant_extracted = bool(target_fixture and agreed_deadline_iso and cost_bearer != "UNRESOLVED")

    if covenant_extracted:
        stmt = f"{sender_role.title()} requests repair of {target_fixture.replace('_', ' ').title()} by {agreed_deadline_iso}, expenses borne by {cost_bearer}."
    elif target_fixture:
        stmt = f"{sender_role.title()} reports {target_fixture.replace('_', ' ').title()} is non-functional and requests repair."
    else:
        stmt = "Tenant submitted an inquiry or complaint."

    return json.dumps({
        "status": "SENTIMENT_NORMALIZED",
        "tenancy_id": tid,
        "neutralized_statement": stmt,
        "covenant_extracted": covenant_extracted,
        "action_type": "REPAIR",
        "target_fixture": target_fixture or "UNKNOWN_FIXTURE",
        "agreed_deadline_iso": agreed_deadline_iso,
        "cost_bearer": cost_bearer,
        "estimated_inr": 1500.0,
        "hostility_score": 0.85 if is_hostile else 0.10,
        "aggression_stripped": is_hostile,
        "threat_flags_stripped": ["RENT_WITHHOLDING_THREAT"] if is_hostile else [],
        "origin_evidence_hash": evidence_hash
    })

@mcp.tool(
    name="generate_it_act_addendum",
    description="Compiles an immutable electronic contract addendum under Section 10A of the Information Technology Act, 2000."
)
async def generate_it_act_addendum(
    tenancy_id: str = Field(description="Unique lease UUID"),
    covenant_json: Any = Field(description="Structured covenant payload string or dictionary"),
    evidence_hash: str = Field(description="Section 63 BSA origin audio_sha256_hash")
) -> str:
    # Handle stringified JSON or direct dictionary input
    cov = json.loads(covenant_json) if isinstance(covenant_json, str) else covenant_json
    if not isinstance(cov, dict):
        cov = {}

    target = cov.get("target_fixture", cov.get("asset_affected", "BATHROOM_GEYSER"))
    deadline = cov.get("agreed_deadline_iso", cov.get("statutory_deadline_hours", "72h"))
    bearer = cov.get("cost_bearer", "LANDLORD")

    addendum_id = f"ADDENDUM_{tenancy_id[:6].upper()}_{hashlib.md5(evidence_hash.encode()).hexdigest()[:6]}"
    clause_text = f"Addendum: Landlord covenants to execute repair of {target} on or before {deadline}. Cost responsibility assigned to {bearer}."
    hash_digest = hashlib.sha256(clause_text.encode()).hexdigest()

    record = {
        "addendum_id": addendum_id,
        "tenancy_id": tenancy_id,
        "contract_clause_markdown": clause_text,
        "legal_binding_basis": "IT_ACT_2000_SEC_10A",
        "requires_dual_confirmation": True,
        "hash_digest": hash_digest,
        "evidence_anchor_sha256": evidence_hash,
        "status": "DRAFTED_AWAITING_COUNTERSIGN",
        "timestamp_utc": datetime.now(timezone.utc).isoformat()
    }
    
    # Commit to shared state
    STATE_STORE.setdefault("covenants", {})[addendum_id] = record
    return json.dumps(record)

@mcp.tool(
    name="dispatch_whatsapp_hsm",
    description="Dispatches a structured WhatsApp Action Card with a 24-hour Notice of Understanding countdown timer."
)
async def dispatch_whatsapp_hsm(
    tenancy_id: str = Field(description="Unique lease UUID"),
    recipient_phone: Optional[str] = Field(default=None, description="Landlord phone with country code e.g. +9198XXXXXXXX"),
    recipient_phone_e164: Optional[str] = Field(default=None, description="Alias for recipient_phone"),
    template_name: str = Field(default="MAINTENANCE_NOTICE_OF_UNDERSTANDING", description="Template identifier"),
    template_type: Optional[str] = Field(default=None, description="Alias for template_name"),
    template_variables: str = Field(default="{}", description="JSON string of template variables"),
    passive_consent_hours: int = Field(default=24, description="Timer window in hours"),
    addendum_id: str = Field(default="ADDENDUM_STAGED", description="Staged addendum UUID")
) -> str:
    target_phone = recipient_phone or recipient_phone_e164 or "+919876543210"
    active_template = template_type or template_name
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(hours=passive_consent_hours)

    return json.dumps({
        "status": "DISPATCHED_AND_ARMED",
        "whatsapp_message_id": f"wamid.HBgL{tenancy_id[:6].upper()}_{int(now.timestamp())}",
        "dispatch_timestamp_utc": now.isoformat(),
        "passive_timer_id": f"TIMER_24H_{addendum_id}",
        "timer_expiry_timestamp_utc": deadline.isoformat(),
        "delivery_status": "DELIVERED",
        "recipient_phone": target_phone,
        "addendum_id": addendum_id,
        "hsm_template": active_template,
        "interactive_buttons": ["APPROVE", "DISPUTE"],
        "passive_consent_hours": passive_consent_hours,
        "legal_rule": "Silence for 24 hours constitutes binding electronic consent under Section 10A IT Act, 2000."
    })
if __name__ == "__main__":
    mcp.run(transport="sse")
