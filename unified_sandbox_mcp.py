import os
import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from mcp.server.fastmcp import FastMCP
from pydantic import Field

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
    tenancy_period_months: int = Field(default=11, description="Lease duration in months"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    auth = verify_grantex_authorization("create_tripartite_vault", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    if deposit_amount_inr > 1000000.0:
        return json.dumps({
            "status": "DEPOSIT_LIMIT_EXCEEDED",
            "error": "DEPOSIT_LIMIT_EXCEEDED: Security deposit exceeds Rs 10,00,000 ceiling. Requires multi-sig KYC approval."
        })
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
    sweep_amount_inr: float = Field(description="Float balance to deploy into overnight sovereign repos"),
    annualized_yield_pct: float = Field(default=6.75, description="Benchmark yield rate"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    auth = verify_grantex_authorization("trigger_treps_sweep", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    daily_yield = round(sweep_amount_inr * (annualized_yield_pct / 100.0) / 365.0, 2)
    landlord_share = round(daily_yield * 0.5, 2)
    platform_share = round(daily_yield - landlord_share, 2)

    if vault_id in STATE_STORE["vaults"]:
        STATE_STORE["vaults"][vault_id]["accrued_yield_inr"] += daily_yield

    return json.dumps({
        "status": "SWEEP_EXECUTED",
        "vault_id": vault_id,
        "swept_amount_inr": sweep_amount_inr,
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
    vault_id: str = Field(description="Tripartite Escrow Vault ID"),
    disputed_amount_inr: float = Field(description="Contested damage delta to be quarantined"),
    dispute_reason: str = Field(description="Grounds for contestation"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    auth = verify_grantex_authorization("lock_dispute_subvault", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    vault = STATE_STORE["vaults"].get(vault_id, {
        "undisputed_balance_inr": 150000.0,
        "disputed_subvault_inr": 0.0
    })

    if disputed_amount_inr > vault["undisputed_balance_inr"]:
        disputed_amount_inr = vault["undisputed_balance_inr"]

    vault["undisputed_balance_inr"] -= disputed_amount_inr
    vault["disputed_subvault_inr"] += disputed_amount_inr
    subvault_id = f"SUBVAULT_DISPUTE_{hashlib.md5(dispute_reason.encode()).hexdigest()[:8]}"

    return json.dumps({
        "status": "SUBVAULT_PARTITIONED",
        "subvault_id": subvault_id,
        "quarantined_amount_inr": disputed_amount_inr,
        "remaining_liquid_inr": vault["undisputed_balance_inr"],
        "odr_escalation_eligible": True
    })

@mcp.tool(
    name="execute_split_payout",
    description="Executes instant H2H IMPS/UPI dual-party disbursement once T-0 QR cryptographic verification clears."
)
async def execute_split_payout(
    vault_id: str = Field(description="Tripartite Escrow Vault ID"),
    tenant_payout_inr: float = Field(description="Liquid release sanctioned to tenant"),
    landlord_payout_inr: float = Field(description="Approved deduction balance paid to landlord"),
    latent_defect_hold_pct: float = Field(default=15.0, description="Float reserved for 7-day Latent Defect Bond"),
    t0_qr_nonce: str = Field(description="Cryptographic nonce verified at key-exchange"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    auth = verify_grantex_authorization("execute_split_payout", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    if not t0_qr_nonce.startswith("NONCE_T0_VALID"):
        return json.dumps({
            "status": "PAYOUT_REJECTED",
            "error": "INVALID_POSSESSION_NONCE: Move-out handover QR was not scanned or is counterfeit."
        })

    bond_hold = round(tenant_payout_inr * (latent_defect_hold_pct / 100.0), 2)
    immediate_tenant_release = round(tenant_payout_inr - bond_hold, 2)

    return json.dumps({
        "status": "SETTLED_TERMINATED",
        "vault_id": vault_id,
        "tenant_immediate_utr": f"PINE_IMPS_{int(datetime.now().timestamp())}_01",
        "tenant_immediate_payout_inr": immediate_tenant_release,
        "latent_defect_bond_hold_inr": bond_hold,
        "landlord_utr": f"PINE_IMPS_{int(datetime.now().timestamp())}_02" if landlord_payout_inr > 0 else "N/A",
        "landlord_payout_inr": landlord_payout_inr,
        "bond_release_timer_utc": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    })

@mcp.tool(
    name="invoke_fldg_deduction",
    description="Liquidates security deposit float directly to the partner NBFC when monthly e-NACH rent debit bounces."
)
async def invoke_fldg_deduction(
    vault_id: str = Field(description="Tripartite Escrow Vault ID"),
    missed_rent_amount_inr: float = Field(description="Contractual monthly rent due"),
    enach_bounce_code: str = Field(description="NPCI failure code (e.g., 'INSUFFICIENT_FUNDS')"),
    grace_period_expired: bool = Field(default=True, description="True if 72-hour grace timer elapsed"),
    grantex_token: Optional[str] = Field(default=None, description="Optional Grantex scoped authorization token")
) -> str:
    auth = verify_grantex_authorization("invoke_fldg_deduction", grantex_token)
    if not auth["authorized"]:
        return json.dumps({"status": "GRANTEX_ACCESS_DENIED", "error": auth["error"], "required_scope": auth["scope_checked"]})
    if not grace_period_expired:
        return json.dumps({
            "status": "FLDG_REJECTED",
            "error": "GRACE_PERIOD_ACTIVE: Cannot liquidate collateral before the 72-hour settlement window lapses."
        })

    return json.dumps({
        "status": "FACTORING_REIMBURSED",
        "vault_id": vault_id,
        "nbfc_settlement_utr": f"NBFC_REIMBURSE_{hashlib.sha256(vault_id.encode()).hexdigest()[:10]}",
        "recovered_amount_inr": missed_rent_amount_inr,
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
        "PAINT_WALL": 24,
        "FLOOR_TILE": 120,
        "FIXTURE_PLUMBING": 60,
        "FIXTURE_ELECTRICAL": 60,
        "CARPENTRY_DOOR": 60
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

        if tenancy_duration_months >= lifespan:
            factor = 0.0
            rationale = f"CPWD statutory lifespan ({lifespan}m) exceeded. Classified as 100% normal wear-and-tear."
        else:
            factor = max(0.0, 1.0 - (tenancy_duration_months / lifespan))
            rationale = f"Depreciated via CPWD schedule ({tenancy_duration_months}/{lifespan} months consumed)."

        allowable = round(raw_cost * factor, 2)
        results.append({
            "surface_category": cat,
            "raw_cost_inr": raw_cost,
            "depreciation_factor": round(factor, 4),
            "allowable_deduction_inr": allowable,
            "statutory_rationale": rationale
        })

    return json.dumps({
        "status": "DEPRECIATION_APPLIED",
        "tenancy_id": tenancy_id,
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

import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from mcp.server.fastmcp import FastMCP
from pydantic import Field

@mcp.tool(
    name="strip_sentiment_bias",
    description="Strips hostility and retaliatory threats, normalizes prose, and dynamically extracts structured legal covenant parameters."
)
async def strip_sentiment_bias(
    tenancy_id: str = Field(description="Unique lease UUID"),
    raw_transcript: Optional[str] = Field(default=None, description="Raw transcript or normalized text"),
    raw_message_text: Optional[str] = Field(default=None, description="Alias for raw_transcript"),
    sender_role: str = Field(default="TENANT", description="TENANT or LANDLORD"),
    evidence_hash: Optional[str] = Field(default="MOCK_HASH_DIGEST", description="Section 63 BSA origin SHA-256 binary hash")
) -> str:
    text = (raw_transcript or raw_message_text or "").strip()
    lower_text = text.lower()

    # 1. Hostility & Retaliatory Threat Detection (General Pattern Lexicon)
    threat_patterns = [
        r"not paying rent", r"rent se kaat", r"rent deduct", r"nahi dunga",
        r"withhold.*rent", r"smash", r"maar dunga", r"thief", r"insane",
        r"useless", r"idiot", r"terrible", r"worst", r"hate living"
    ]
    threats_found = [p for p in threat_patterns if re.search(p, lower_text)]
    is_hostile = len(threats_found) > 0 or ("!" in text and any(w in lower_text for w in ["insane", "thief", "idiot"]))

    # 2. Dynamic Fixture & Surface Catalog Extraction
    fixture_map = {
        "geyser": "BATHROOM_GEYSER",
        "ac": "AIR_CONDITIONER",
        "air conditioner": "AIR_CONDITIONER",
        "tap": "BATHROOM_TAP",
        "plumber": "PLUMBING_FIXTURE",
        "fan": "CEILING_FAN",
        "tile": "FLOOR_TILE",
        "door": "WOODEN_DOOR",
        "window": "GLASS_WINDOW",
        "wall": "PAINT_WALL",
        "painting": "PAINT_WALL"
    }
    extracted_fixtures = []
    for keyword, fixture_id in fixture_map.items():
        if re.search(r"\b" + re.escape(keyword) + r"\b", lower_text):
            if fixture_id not in extracted_fixtures:
                extracted_fixtures.append(fixture_id)

    target_fixture = extracted_fixtures[0] if extracted_fixtures else None

    # 3. Dynamic Date & Deadline Extraction
    # Handles: "6 October 2026", "2026-10-06", "8 October 2026", "09 October 2026", etc.
    iso_date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    written_date_match = re.search(
        r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+(\d{4}))?\b",
        lower_text
    )

    agreed_deadline_iso = None
    if iso_date_match:
        agreed_deadline_iso = iso_date_match.group(1)
    elif written_date_match:
        day = written_date_match.group(1).zfill(2)
        month_name = written_date_match.group(2).capitalize()
        year = written_date_match.group(3) or "2026"
        try:
            parsed_dt = datetime.strptime(f"{day} {month_name} {year}", "%d %B %Y")
            agreed_deadline_iso = parsed_dt.strftime("%Y-%m-%d")
        except Exception:
            agreed_deadline_iso = f"{year}-10-{day}"

    # 4. Dynamic Cost Bearer Allocation
    cost_bearer = "UNRESOLVED"
    if re.search(r"\b(landlord will pay|landlord ka kharcha|landlord pay|owner will pay|owner pays|landlord pays)\b", lower_text):
        cost_bearer = "LANDLORD"
    elif re.search(r"\b(tenant will pay|i will pay|my expense|my cost|main dunga|nane kodthini)\b", lower_text):
        cost_bearer = "TENANT"
    elif re.search(r"\b(split|50-50|share cost|half)\b", lower_text):
        cost_bearer = "SPLIT"

    # 5. Covenant Validation Gate (CV4 Compliance)
    # True ONLY when fixture, deadline, and cost bearer are all unambiguously present
    covenant_extracted = bool(target_fixture and agreed_deadline_iso and cost_bearer != "UNRESOLVED")

    # 6. Objective Neutralization
    action_type = "REPLACE" if any(w in lower_text for w in ["replace", "badal", "naya"]) else "REPAIR"
    fixture_display = (target_fixture or "fixture").replace("_", " ").title()

    if covenant_extracted:
        neutralized_statement = f"{sender_role.title()} requests {action_type.lower()} of {fixture_display} by {agreed_deadline_iso}, with expenses allocated to {cost_bearer}."
    elif target_fixture:
        neutralized_statement = f"{sender_role.title()} reports {fixture_display} is non-functional and requests repair."
    else:
        neutralized_statement = f"{sender_role.title()} submitted a general inquiry or unstructured complaint."

    return json.dumps({
        "status": "SENTIMENT_NORMALIZED",
        "tenancy_id": tenancy_id,
        "neutralized_statement": neutralized_statement,
        "covenant_extracted": covenant_extracted,
        "action_type": action_type,
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
    "interactive_buttons": ["APPROVE", "DISPUTE"]
})
if __name__ == "__main__":
    mcp.run(transport="sse")
