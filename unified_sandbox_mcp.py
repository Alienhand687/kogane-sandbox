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
    "covenants": {}
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
    tenancy_period_months: int = Field(default=11, description="Lease duration in months")
) -> str:
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
        "status": "VAULT_LOCKED",
        "created_at_utc": datetime.now(timezone.utc).isoformat()
    }
    STATE_STORE["vaults"][vault_id] = record
    STATE_STORE["tenancies"][tenancy_id] = {"vault_id": vault_id, "status": "ACTIVE_TENANCY"}
    return json.dumps({"status": "VAULT_INITIALIZED", **record})

@mcp.tool(
    name="trigger_treps_sweep",
    description="Simulates daily CCIL Tri-Party Repo (TREPS) sovereign overnight sweeps (yielding 6.5%-7.0% p.a.)."
)
async def trigger_treps_sweep(
    vault_id: str = Field(description="Tripartite Escrow Vault identifier"),
    sweep_amount_inr: float = Field(description="Float balance to deploy into overnight sovereign repos"),
    annualized_yield_pct: float = Field(default=6.75, description="Benchmark yield rate")
) -> str:
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
    dispute_reason: str = Field(description="Grounds for contestation")
) -> str:
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
    t0_qr_nonce: str = Field(description="Cryptographic nonce verified at key-exchange")
) -> str:
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
    grace_period_expired: bool = Field(default=True, description="True if 72-hour grace timer elapsed")
) -> str:
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
    inspection_type: str = Field(default="MOVE_OUT_AUDIT", description="'MOVE_OUT_AUDIT' or 'SUPERVISORY_RESCAN'")
) -> str:
    if pincode == "000000":
        return json.dumps({"status": "SERVICEABILITY_DEFICIT", "error": "PIN code not serviceable by primary fleet."})

    return json.dumps({
        "status": "DISPATCHED",
        "waybill": f"DEL_RVP_{pincode}_{tenancy_id[:6].upper()}",
        "assigned_agent_id": "DEL_AGENT_BLR_404",
        "eta": "25 mins (Simulated)",
        "inspection_protocol": "BLIND_AR_SLAM_SWEEP"
    })

@mcp.tool(
    name="ingest_mesh_baseline",
    description="Validates WebAR move-in spatial baseline coverage (must be >= 98.0%) and locks the SHA-256 hash."
)
async def ingest_mesh_baseline(
    tenancy_id: str = Field(description="Unique lease UUID"),
    video_stream_s3_uri: str = Field(description="S3 bucket path to video sweep"),
    imu_spatial_data_s3_uri: str = Field(description="S3 bucket path to IMU sensors")
) -> str:
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
    tolerance_threshold_mm: float = Field(default=3.0)
) -> str:
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
    raw_anomalies: str = Field(description="JSON array of anomalies or string representation")
) -> str:
    anomalies_list = json.loads(raw_anomalies) if isinstance(raw_anomalies, str) else raw_anomalies
    results = []

    for item in anomalies_list:
        cat = item.get("surface_category", "UNKNOWN")
        raw_cost = item.get("raw_repair_cost_inr", item.get("claimed_repair_cost_inr", 0.0))

        lifespan = 24 if cat == "PAINT_WALL" else (120 if cat == "FLOOR_TILE" else 60)

        if tenancy_duration_months >= lifespan:
            factor = 0.0
            rationale = f"CPWD statutory lifespan ({lifespan}m) exceeded. Classified as 100% normal wear-and-tear."
        else:
            factor = round(1.0 - (tenancy_duration_months / lifespan), 2)
            rationale = f"Depreciated via CPWD schedule ({tenancy_duration_months}/{lifespan} months consumed)."

        allowable = round(raw_cost * factor, 2)
        results.append({
            "surface_category": cat,
            "raw_cost_inr": raw_cost,
            "depreciation_factor": factor,
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
    repair_item_code: str = Field(description="Standardized repair fixture identifier")
) -> str:
    rate_table = {
        "PAINTING": {"labor": 1200.0, "material": 1800.0, "total": 3000.0},
        "FLOORING": {"labor": 1500.0, "material": 2500.0, "total": 4000.0},
        "PLUMBING": {"labor": 450.0, "material": 350.0, "total": 800.0},
        "ELECTRICAL": {"labor": 500.0, "material": 600.0, "total": 1100.0}
    }
    caps = rate_table.get(trade_category.upper(), {"labor": 500.0, "material": 500.0, "total": 1000.0})
    return json.dumps({
        "pincode": pincode,
        "trade_category": trade_category,
        "max_allowable_labor_inr": caps["labor"],
        "max_allowable_material_inr": caps["material"],
        "total_ceiling_cap_inr": caps["total"]
    })

# ============================================================================
# AGENT 3: COVENANT & LEGAL TOOLS (GNANI / IT ACT / WHATSAPP HSM)
# ============================================================================

@mcp.tool(
    name="transcribe_gnani_asr",
    description="Simulates Gnani.ai Indic Speech-to-Text transcription and anchors raw audio hashes under Section 63 BSA 2023."
)
async def transcribe_gnani_asr(
    tenancy_id: str = Field(description="Unique lease UUID"),
    raw_audio_s3_uri: str = Field(description="S3 bucket URI of recorded audio file"),
    source_language_hint: str = Field(default="hi-IN", description="Language code: hi-IN, kn-IN, ta-IN, te-IN")
) -> str:
    mock_audio_hash = hashlib.sha256(raw_audio_s3_uri.encode()).hexdigest()
    
    transcripts = {
        "hi-IN": "Dekho bhaiya, geyser pichle teen din se kharab hai. Agar Friday tak theek nahi karwaya toh rent se kaat lunga.",
        "kn-IN": "Nodi sir, geyser repair agilla. Friday olage sari madlilla andre nanu rent deduct madtini.",
        "en-IN": "The geyser has been leaking for three days. If you do not fix it by Friday, I will deduct it from next month's rent."
    }
    raw_text = transcripts.get(source_language_hint, transcripts["hi-IN"])

    return json.dumps({
        "status": "TRANSCRIPTION_SUCCESS",
        "tenancy_id": tenancy_id,
        "detected_language": source_language_hint,
        "acoustic_confidence": 0.94,
        "raw_transcript": raw_text,
        "bsa_section_63_evidence_hash": mock_audio_hash
    })

@mcp.tool(
    name="strip_sentiment_bias",
    description="Strips hostility, retaliation, and passive-aggression from transcripts to extract objective maintenance parameters."
)
async def strip_sentiment_bias(
    raw_transcript: str = Field(description="Raw speech-to-text transcript"),
    evidence_hash: str = Field(description="Section 63 BSA origin SHA-256 binary hash")
) -> str:
    return json.dumps({
        "status": "SENTIMENT_NORMALIZED",
        "hostility_detected": True,
        "threat_flags_stripped": ["RENT_WITHHOLDING_THREAT", "RETALIATORY_ESCALATION"],
        "extracted_covenant": {
            "asset_affected": "BATHROOM_GEYSER",
            "required_action": "REPAIR_OR_REPLACE",
            "statutory_deadline_hours": 72,
            "cost_bearer": "LANDLORD",
            "origin_evidence_hash": evidence_hash
        }
    })

@mcp.tool(
    name="generate_it_act_addendum",
    description="Compiles an immutable electronic contract addendum under Section 10A of the Information Technology Act, 2000."
)
async def generate_it_act_addendum(
    tenancy_id: str = Field(description="Unique lease UUID"),
    covenant_json: str = Field(description="Structured covenant payload string"),
    evidence_hash: str = Field(description="Section 63 BSA origin hash")
) -> str:
    cov = json.loads(covenant_json) if isinstance(covenant_json, str) else covenant_json
    addendum_id = f"ADDENDUM_{tenancy_id[:6].upper()}_{hashlib.md5(evidence_hash.encode()).hexdigest()[:6]}"
    
    record = {
        "addendum_id": addendum_id,
        "tenancy_id": tenancy_id,
        "statutory_framework": "Section 10A, Information Technology Act, 2000",
        "covenant_summary": f"Landlord commits to repair/replace {cov.get('asset_affected', 'FIXTURE')} within {cov.get('statutory_deadline_hours', 48)} hours.",
        "passive_consent_rule": "24h Notice of Understanding (Silence constitutes digital ratification)",
        "evidence_anchor_sha256": evidence_hash,
        "timestamp_utc": datetime.now(timezone.utc).isoformat()
    }
    STATE_STORE["covenants"][addendum_id] = record
    return json.dumps({"status": "ADDENDUM_STAGED", **record})

@mcp.tool(
    name="dispatch_whatsapp_hsm",
    description="Simulates WhatsApp Action Card dispatch with a 24-hour passive consent Notice of Understanding countdown timer."
)
async def dispatch_whatsapp_hsm(
    tenancy_id: str = Field(description="Unique lease UUID"),
    counterparty_phone: str = Field(description="E.164 phone number (+91...)"),
    addendum_id: str = Field(description="Staged Addendum UUID"),
    template_type: str = Field(default="NOTICE_OF_UNDERSTANDING_MAINTENANCE")
) -> str:
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(hours=24)

    return json.dumps({
        "status": "DISPATCHED_AND_ARMED",
        "tenancy_id": tenancy_id,
        "recipient": counterparty_phone,
        "addendum_id": addendum_id,
        "hsm_template": template_type,
        "interactive_buttons": ["APPROVE_REPAIR", "DISPUTE_DELTA"],
        "passive_consent_deadline_utc": deadline.isoformat(),
        "timer_armed": True,
        "legal_implication": "If no dispute is logged before deadline, Section 10A covenant becomes binding automatically."
    })

if __name__ == "__main__":
    mcp.run(transport="sse")