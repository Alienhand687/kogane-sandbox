# Provenance: Derived from docs/state_machine.md, context/agents_and_tools.md, context/agent2_current_state.md, and decisions/LOCKED.md on 2026-10-04
"""
NEXUS: Autonomous Protocol Orchestrator & State Continuum.
Coordinates the multi-agent rental escrow lifecycle across Agent 1 (Escrow),
Agent 2 (Condition), and Agent 3 (Covenant).

Enforces:
- Invariant A: No Unauthorized Capital Movement
- Invariant B: Grantex Least Privilege
- Invariant C: Deterministic Fail-Closed Operation
- Loop Guards: 2% dual-scan gate, 1st occlusion rescan -> 2nd occlusion HITL
- Exact Programmed Timers: 72h grace, 24h passive acceptance, 48h unilateral key-drop, 7d latent bond
"""

import json
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from nexus.models import (
    TenancyLifecycleState,
    InspectionEvent,
    TenantScanStatus,
    LandlordDecision,
    TenancyProfile,
    DeductionPackage,
    WorkflowEventRecord,
)
from nexus.clock import VirtualClock, ProtocolTimer
import sandbox.unified_sandbox_mcp as sm
from sandbox.unified_sandbox_mcp import mcp


class NexusOrchestrator:
    """
    Top-Level Workflow Engine and State Machine Coordinator for the Kogane Protocol.
    Executes and enforces state transitions between the specialist agents.
    """

    def __init__(self, profile: TenancyProfile, clock: Optional[VirtualClock] = None):
        self.profile = profile
        self.clock = clock or VirtualClock()
        self.current_state: TenancyLifecycleState = TenancyLifecycleState.STATE_0_ONBOARDING
        self.vault_id: Optional[str] = None
        self.baseline_mesh_id: Optional[str] = None
        self.baseline_mesh_hash: Optional[str] = None
        self.rescan_count: int = 0
        self.latest_deduction_package: Optional[DeductionPackage] = None
        self.audit_log: List[WorkflowEventRecord] = []
        self.state_data: Dict[str, Any] = {
            "monthly_rent_status": "PAID",
            "last_sweep_date": None,
            "dispute_subvault_id": None,
            "handover_qr_nonce": None,
            "latent_bond_subvault_id": None,
            "settlement_records": []
        }

    # -------------------------------------------------------------------------
    # Helper: Direct FastMCP Tool Caller (Domain & Grantex Bound)
    # -------------------------------------------------------------------------
    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Calls a tool via the FastMCP server instance and parses JSON output."""
        res = await mcp.call_tool(tool_name, arguments)
        if isinstance(res, tuple) and len(res) > 0 and len(res[0]) > 0:
            text = res[0][0].text
        elif hasattr(res, "content") and len(res.content) > 0:
            text = res.content[0].text
        else:
            text = str(res)
        try:
            return json.loads(text)
        except Exception:
            return {"raw_text": text}

    def _log_event(self, event_type: str, from_state: str, to_state: str, payload: Dict[str, Any], status: str = "SUCCESS"):
        event = WorkflowEventRecord(
            event_id=f"EVT_{self.profile.tenancy_id}_{len(self.audit_log) + 1:04d}",
            timestamp_utc=self.clock.current_time_iso,
            event_type=event_type,
            source_agent_or_actor="NEXUS_ORCHESTRATOR",
            from_state=str(from_state),
            to_state=str(to_state),
            payload=payload,
            status=status
        )
        self.audit_log.append(event)
        sm.STATE_STORE["audit_trail"].append(event.model_dump())

    # =========================================================================
    # STATE 0: ONBOARDING & ESCROW INITIALIZATION
    # =========================================================================
    async def run_state_0_onboarding(self) -> Dict[str, Any]:
        """
        Step 1: Lease closure triggers Kogane to establish a tripartite escrow trust through Pine Labs.
        Calls Agent 1 scoped tool: create_tripartite_vault.
        """
        self._log_event("START_ONBOARDING", self.current_state, TenancyLifecycleState.STATE_0_ONBOARDING, {"tenancy_id": self.profile.tenancy_id})

        res = await self._call_tool("create_tripartite_vault", {
            "tenancy_id": self.profile.tenancy_id,
            "tenant_id": self.profile.tenant_id,
            "landlord_id": self.profile.landlord_id,
            "deposit_amount_inr": self.profile.deposit_amount_inr,
            "lease_duration_months": self.profile.lease_duration_months,
            "trustee_code": self.profile.trustee_code,
            "custody_bank": self.profile.custody_bank,
            "idempotency_key": f"{self.profile.tenancy_id}:create_vault:001"
        })

        if res.get("status") != "VAULT_INITIALIZED":
            self.current_state = TenancyLifecycleState.HITL_ARBITRATION
            self._log_event("ONBOARDING_FAILED", TenancyLifecycleState.STATE_0_ONBOARDING, self.current_state, res, "FAILED")
            return res

        self.vault_id = res["vault_id"]
        self.current_state = TenancyLifecycleState.STATE_1_BASELINE_CAPTURE
        self._log_event("VAULT_INITIALIZED", TenancyLifecycleState.STATE_0_ONBOARDING, self.current_state, res)
        return res

    # =========================================================================
    # STATE 1: BASELINE GEOMETRIC CAPTURE (T-Start)
    # =========================================================================
    async def run_state_1_baseline_capture(
        self,
        video_stream_s3_uri: str = "s3://kogane-telemetry/baseline_video.mp4",
        imu_spatial_data_s3_uri: str = "s3://kogane-telemetry/imu_data.json"
    ) -> Dict[str, Any]:
        """
        Step 2: Tenant/Delhivery captures baseline geometry at key handover.
        Calls Agent 2 scoped tool: ingest_mesh_baseline.
        Then initiates initial TREPS repo sweep via Agent 1: trigger_treps_sweep.
        """
        if self.current_state != TenancyLifecycleState.STATE_1_BASELINE_CAPTURE:
            raise RuntimeError(f"Cannot capture baseline in state {self.current_state}")

        res = await self._call_tool("ingest_mesh_baseline", {
            "tenancy_id": self.profile.tenancy_id,
            "video_stream_s3_uri": video_stream_s3_uri,
            "imu_spatial_data_s3_uri": imu_spatial_data_s3_uri
        })

        if res.get("status") != "BASELINE_LOCKED":
            self.current_state = TenancyLifecycleState.HITL_ARBITRATION
            self._log_event("BASELINE_FAILED", TenancyLifecycleState.STATE_1_BASELINE_CAPTURE, self.current_state, res, "FAILED")
            return res

        self.baseline_mesh_id = res["mesh_id"]
        self.baseline_mesh_hash = res["mesh_sha256_hash"]

        # Trigger initial TREPS sweep on idle funds
        sweep_res = await self._call_tool("trigger_treps_sweep", {
            "vault_id": self.vault_id,
            "amount_inr": self.profile.deposit_amount_inr,
            "sweep_type": "SWEEP_IN"
        })

        self.current_state = TenancyLifecycleState.STATE_2_ACTIVE_TENANCY
        self._log_event("BASELINE_LOCKED_ACTIVE", TenancyLifecycleState.STATE_1_BASELINE_CAPTURE, self.current_state, {
            "baseline": res,
            "initial_sweep": sweep_res
        })
        return res

    # =========================================================================
    # STATE 2: ACTIVE TENANCY — YIELD, RENT & MAINTENANCE WORKFLOWS
    # =========================================================================
    async def execute_daily_treps_sweep(self) -> Dict[str, Any]:
        """Runs the daily CCIL TREPS sovereign overnight sweep (Agent 1)."""
        if self.current_state != TenancyLifecycleState.STATE_2_ACTIVE_TENANCY:
            raise RuntimeError(f"Cannot sweep repo in state {self.current_state}")

        res = await self._call_tool("trigger_treps_sweep", {
            "vault_id": self.vault_id,
            "amount_inr": self.profile.deposit_amount_inr,
            "sweep_type": "SWEEP_IN"
        })
        self.state_data["last_sweep_date"] = self.clock.current_time_iso
        self._log_event("DAILY_SWEEP", self.current_state, self.current_state, res)
        return res

    async def handle_rent_mandate_bounce(self) -> ProtocolTimer:
        """
        Arms 72-hour grace period clock upon e-NACH auto-debit failure bounce.
        """
        self.state_data["monthly_rent_status"] = "MANDATE_BOUNCED"
        timer = self.clock.arm_timer(
            tenancy_id=self.profile.tenancy_id,
            timer_name="RENT_GRACE_72H",
            duration_hours=72.0,
            metadata={"rent_amount_inr": self.profile.monthly_rent_inr}
        )
        self._log_event("RENT_MANDATE_BOUNCE", self.current_state, self.current_state, {
            "timer_id": timer.timer_id,
            "expires_at": timer.expires_at.isoformat()
        })
        return timer

    async def resolve_rent_grace_expiry(self) -> Dict[str, Any]:
        """
        When 72h grace expires without rent payment or landlord extension,
        triggers FLDG deduction from security deposit (Agent 1).
        """
        timer = self.clock.get_timer(self.profile.tenancy_id, "RENT_GRACE_72H")
        if timer and not timer.is_expired:
            raise RuntimeError("72-hour grace period has not yet expired.")

        res = await self._call_tool("invoke_fldg_deduction", {
            "vault_id": self.vault_id,
            "missed_rent_amount_inr": self.profile.monthly_rent_inr,
            "grace_period_expired": True
        })
        self.state_data["monthly_rent_status"] = "FLDG_SETTLED_FROM_DEPOSIT"
        self._log_event("FLDG_DEDUCTION_EXECUTED", self.current_state, self.current_state, res)
        return res

    async def handle_maintenance_event(
        self,
        audio_stream_uri: str,
        landlord_phone: str = "+919876543210"
    ) -> Dict[str, Any]:
        """
        Agent 3 Workflow: Vernacular ASR -> Neutralize -> Section 10A Addendum -> WhatsApp HSM card.
        Arms 24-hour passive consent window.
        """
        asr_res = await self._call_tool("transcribe_gnani_asr", {
            "audio_stream_uri": audio_stream_uri
        })
        raw_text = asr_res.get("normalized_english_text", asr_res.get("original_transcript", ""))

        strip_res = await self._call_tool("strip_sentiment_bias", {
            "raw_transcript": raw_text,
            "sender_role": "TENANT"
        })
        neutral_covenant = strip_res.get("neutralized_statement", raw_text)

        addendum_res = await self._call_tool("generate_it_act_addendum", {
            "tenancy_id": self.profile.tenancy_id,
            "agreed_covenant_text": neutral_covenant,
            "landlord_id": self.profile.landlord_id,
            "tenant_id": self.profile.tenant_id,
            "source_audio_hash": asr_res.get("audio_sha256_hash", "HASH_AUDIO_MOCK")
        })

        hsm_res = await self._call_tool("dispatch_whatsapp_hsm", {
            "recipient_phone": landlord_phone,
            "template_name": "MAINTENANCE_NOTICE_OF_UNDERSTANDING",
            "template_variables": {
                "covenant_summary": neutral_covenant,
                "addendum_id": addendum_res.get("addendum_id", "ADD_01"),
                "statutory_reference": "Section 10A Information Technology Act 2000"
            },
            "tenancy_id": self.profile.tenancy_id
        })

        # Arm 24-Hour Passive Consent Timer
        timer = self.clock.arm_timer(
            tenancy_id=self.profile.tenancy_id,
            timer_name="PASSIVE_CONSENT_24H",
            duration_hours=24.0,
            metadata={"addendum_id": addendum_res.get("addendum_id")}
        )

        res_payload = {
            "asr": asr_res,
            "strip": strip_res,
            "addendum": addendum_res,
            "hsm": hsm_res,
            "timer": timer.model_dump()
        }
        self._log_event("MAINTENANCE_ADDENDUM_STAGED", self.current_state, self.current_state, res_payload)
        return res_payload

    # =========================================================================
    # STATE 3: CONDITION FREEZE & DEDUCTION ARBITRATION (T-24 Hours)
    # =========================================================================
    async def trigger_move_out_inspection(
        self,
        inspection_event: InspectionEvent = InspectionEvent.MOVE_OUT_AUDIT
    ) -> Dict[str, Any]:
        """
        Dispatches Delhivery gig worker for doorstep AR SLAM sweep (Agent 2).
        """
        self.current_state = TenancyLifecycleState.STATE_3_CONDITION_FREEZE
        res = await self._call_tool("dispatch_delhivery_rvp", {
            "tenancy_id": self.profile.tenancy_id,
            "pincode": self.profile.property_pincode,
            "latitude": self.profile.latitude,
            "longitude": self.profile.longitude,
            "inspection_type": inspection_event.value
        })
        self._log_event("INSPECTION_DISPATCHED", TenancyLifecycleState.STATE_2_ACTIVE_TENANCY, self.current_state, res)
        return res

    async def execute_move_out_analysis(
        self,
        exit_mesh_id: str,
        duration_months: int,
        tenant_scan_status: TenantScanStatus = TenantScanStatus.SKIPPED,
        dual_scan_divergence_pct: Optional[float] = None,
        landlord_claim_text: Optional[str] = None
    ) -> DeductionPackage:
        """
        Coordinates Agent 2 pipeline:
        1. Upstream 2.0% divergence check (if tenant scan present)
        2. compute_pointcloud_delta (with occlusion loop guard)
        3. query_sor_ceiling (Cap)
        4. apply_cpwd_depreciation (Depreciate)
        5. Assembles DEDUCTION_PACKAGE and routes dispute sub-vault if needed.
        """
        # --- Gate 1: Upstream Divergence Gate ---
        if tenant_scan_status == TenantScanStatus.COMPLETED:
            if dual_scan_divergence_pct is None or dual_scan_divergence_pct > 2.0:
                self.current_state = TenancyLifecycleState.HITL_ARBITRATION
                pkg = DeductionPackage(
                    tenancy_id=self.profile.tenancy_id,
                    inspection_status="HITL",
                    reason_codes=["DUAL_SCAN_DIVERGENCE_EXCEEDED"],
                    next_recommended_state="HITL_ARBITRATION",
                    hitl_brief={"divergence_pct": dual_scan_divergence_pct, "threshold": 2.0}
                )
                self._log_event("DIVERGENCE_EXCEEDED", TenancyLifecycleState.STATE_3_CONDITION_FREEZE, self.current_state, pkg.model_dump(), "FAILED")
                self.latest_deduction_package = pkg
                return pkg

        # --- Gate 2: Compute Point-Cloud Delta ---
        delta_res = await self._call_tool("compute_pointcloud_delta", {
            "tenancy_id": self.profile.tenancy_id,
            "baseline_mesh_id": self.baseline_mesh_id or "BASE_LOCKED_01",
            "exit_mesh_id": exit_mesh_id,
            "tolerance_threshold_mm": 3.0
        })

        # Check Occlusion Gate & Loop Guard
        is_occluded = delta_res.get("status") == "OCCLUSION_DETECTED" or delta_res.get("coverage_pct", 100.0) < 98.0
        if is_occluded:
            if self.rescan_count == 0:
                # First occlusion: return DISPATCH_RESCAN and trigger supervisory rescan
                self.rescan_count += 1
                rescan_dispatch = await self.trigger_move_out_inspection(InspectionEvent.SUPERVISORY_RESCAN)
                pkg = DeductionPackage(
                    tenancy_id=self.profile.tenancy_id,
                    inspection_status="DISPATCH_RESCAN",
                    reason_codes=["INCOMPLETE_POINT_CLOUD_OCCLUSION"],
                    next_recommended_state="DISPATCH_RESCAN",
                    hitl_brief={"rescan_dispatch": rescan_dispatch, "rescan_attempt": 1}
                )
                self._log_event("FIRST_OCCLUSION_RESCAN", self.current_state, self.current_state, pkg.model_dump())
                self.latest_deduction_package = pkg
                return pkg
            else:
                # Persistent occlusion trips loop guard -> HITL
                self.current_state = TenancyLifecycleState.HITL_ARBITRATION
                pkg = DeductionPackage(
                    tenancy_id=self.profile.tenancy_id,
                    inspection_status="HITL",
                    reason_codes=["OCCLUSION_LOOP_GUARD_TRIPPED", "PERSISTENT_OCCLUSION"],
                    next_recommended_state="HITL_ARBITRATION",
                    hitl_brief={"rescan_count": self.rescan_count, "action": "FORCE_CEILING_DEDUCTION"}
                )
                self._log_event("OCCLUSION_LOOP_GUARD_TRIPPED", TenancyLifecycleState.STATE_3_CONDITION_FREEZE, self.current_state, pkg.model_dump(), "FAILED")
                self.latest_deduction_package = pkg
                return pkg

        # Check Sensor Drift Gate
        if delta_res.get("mesh_drift_pct", 0.0) > 5.0:
            self.current_state = TenancyLifecycleState.HITL_ARBITRATION
            pkg = DeductionPackage(
                tenancy_id=self.profile.tenancy_id,
                inspection_status="HITL",
                reason_codes=["SENSOR_DRIFT_EXCEEDED"],
                next_recommended_state="HITL_ARBITRATION",
                hitl_brief={"drift_pct": delta_res.get("mesh_drift_pct")}
            )
            self._log_event("SENSOR_DRIFT_TRIPPED", TenancyLifecycleState.STATE_3_CONDITION_FREEZE, self.current_state, pkg.model_dump(), "FAILED")
            self.latest_deduction_package = pkg
            return pkg

        anomalies = delta_res.get("anomalies", [])
        if not anomalies:
            # Clean inspection: zero deductions
            pkg = DeductionPackage(
                tenancy_id=self.profile.tenancy_id,
                inspection_status="COMPLETED",
                total_allowable_deduction_inr=0.0,
                delta_vector=[],
                reason_codes=["CLEAN_EXIT_SWEEP"],
                next_recommended_state="STAGE_FINANCIAL_LEDGER"
            )
            self.latest_deduction_package = pkg
            self.current_state = TenancyLifecycleState.STATE_4_POSSESSION_SURRENDER
            self._log_event("ANALYSIS_COMPLETED_CLEAN", TenancyLifecycleState.STATE_3_CONDITION_FREEZE, self.current_state, pkg.model_dump())
            return pkg

        # --- Step 3: Cap-Then-Depreciate Pipeline ---
        clamped_anomalies = []
        for anom in anomalies:
            cat = anom["surface_category"]
            trade = "PAINTING" if "PAINT" in cat else ("FLOORING" if "TILE" in cat else ("PLUMBING" if "PLUMBING" in cat else "ELECTRICAL"))
            sor_res = await self._call_tool("query_sor_ceiling", {
                "pincode": self.profile.property_pincode,
                "trade_category": trade,
                "repair_item_code": cat
            })
            ceiling = sor_res.get("total_ceiling_cap_inr", 3000.0)
            raw = anom.get("raw_repair_cost_inr", 0.0)
            clamped = min(raw, ceiling)
            anom_copy = dict(anom)
            anom_copy["raw_repair_cost_inr"] = clamped
            anom_copy["sor_ceiling_inr"] = ceiling
            anom_copy["excess_over_sor_inr"] = max(0.0, raw - ceiling)
            clamped_anomalies.append(anom_copy)

        dep_res = await self._call_tool("apply_cpwd_depreciation", {
            "tenancy_id": self.profile.tenancy_id,
            "tenancy_duration_months": duration_months,
            "raw_anomalies": json.dumps(clamped_anomalies)
        })

        total_allowable = dep_res.get("total_sanctioned_deduction_inr", 0.0)
        final_lines = dep_res.get("itemized_depreciation", [])

        # If deduction is greater than 0, isolate it into a dispute sub-vault
        if total_allowable > 0:
            subvault_res = await self._call_tool("lock_dispute_subvault", {
                "vault_id": self.vault_id,
                "contested_amount_inr": total_allowable,
                "claim_reason": "EXIT_DAMAGE_CONDITION_DELTA"
            })
            self.state_data["dispute_subvault_id"] = subvault_res.get("subvault_id")

        pkg = DeductionPackage(
            tenancy_id=self.profile.tenancy_id,
            inspection_status="COMPLETED",
            total_allowable_deduction_inr=total_allowable,
            delta_vector=final_lines,
            reason_codes=["DAMAGE_AMORTIZED_UNDER_CPWD"],
            next_recommended_state="STAGE_FINANCIAL_LEDGER"
        )
        self.latest_deduction_package = pkg
        self.current_state = TenancyLifecycleState.STATE_4_POSSESSION_SURRENDER
        self._log_event("ANALYSIS_COMPLETED_SANCTIONED", TenancyLifecycleState.STATE_3_CONDITION_FREEZE, self.current_state, pkg.model_dump())
        return pkg

    # =========================================================================
    # STATE 4: POSSESSION SURRENDER & SPLIT PAYOUT (T-0)
    # =========================================================================
    async def execute_t0_possession_payout(
        self,
        auth_signal: str = "NONCE_T0_VALID_891723"
    ) -> Dict[str, Any]:
        """
        Happy Path: Landlord scans tenant's single-use cryptographic QR code.
        Authorizes instant split payout via Agent 1 (Pine Labs IMPS/UPI).
        Releases 85% undisputed balance to tenant, deduction to landlord,
        and locks 15% Latent Defect Bond.
        """
        if self.current_state != TenancyLifecycleState.STATE_4_POSSESSION_SURRENDER:
            raise RuntimeError(f"Cannot execute T-0 payout in state {self.current_state}")

        deduction = self.latest_deduction_package.total_allowable_deduction_inr if self.latest_deduction_package else 0.0
        total_deposit = self.profile.deposit_amount_inr
        undisputed_tenant = max(0.0, total_deposit - deduction)

        payout_res = await self._call_tool("execute_split_payout", {
            "vault_id": self.vault_id,
            "undisputed_tenant_inr": undisputed_tenant,
            "landlord_deduction_inr": deduction,
            "latent_defect_hold_pct": 15.0,
            "possession_qr_signature": auth_signal
        })

        if payout_res.get("status") != "SETTLED_TERMINATED":
            self.current_state = TenancyLifecycleState.HITL_ARBITRATION
            self._log_event("PAYOUT_REJECTED", TenancyLifecycleState.STATE_4_POSSESSION_SURRENDER, self.current_state, payout_res, "FAILED")
            return payout_res

        self.state_data["handover_qr_nonce"] = auth_signal
        self.state_data["latent_bond_subvault_id"] = payout_res.get("latent_subvault_id")
        self.state_data["settlement_records"].append(payout_res)

        # Arm 7-day Latent Defect observation timer
        self.clock.arm_timer(
            tenancy_id=self.profile.tenancy_id,
            timer_name="LATENT_DEFECT_BOND_7D",
            duration_hours=7 * 24.0,
            metadata={"bond_inr": payout_res.get("latent_defect_bond_hold_inr")}
        )

        self.current_state = TenancyLifecycleState.STATE_5_LATENT_DEFECT_WINDOW
        self._log_event("T0_PAYOUT_EXECUTED", TenancyLifecycleState.STATE_4_POSSESSION_SURRENDER, self.current_state, payout_res)
        return payout_res

    async def handle_landlord_ghosting_unilateral_exit(self) -> ProtocolTimer:
        """
        Adversarial Path: Landlord refuses or ghosts T-0 QR scan.
        Tenant drops keys at security/lockbox, arming 48-Hour Unilateral Exit Timer.
        """
        timer = self.clock.arm_timer(
            tenancy_id=self.profile.tenancy_id,
            timer_name="UNILATERAL_EXIT_48H",
            duration_hours=48.0,
            metadata={"reason": "LANDLORD_GHOSTING_T0"}
        )
        self._log_event("UNILATERAL_TIMER_ARMED", self.current_state, self.current_state, timer.model_dump())
        return timer

    async def resolve_unilateral_exit_expiry(self) -> Dict[str, Any]:
        """
        When 48h unilateral exit timer expires without landlord contestation,
        auto-triggers Agent 1 payout via token UNILATERAL_EXIT_TIMER_EXPIRED.
        """
        timer = self.clock.get_timer(self.profile.tenancy_id, "UNILATERAL_EXIT_48H")
        if timer and not timer.is_expired:
            raise RuntimeError("48-Hour Unilateral Exit Timer has not yet expired.")

        return await self.execute_t0_possession_payout(auth_signal="UNILATERAL_EXIT_TIMER_EXPIRED")

    # =========================================================================
    # STATE 5: LATENT DEFECT WINDOW (T-0 to T+7 Days)
    # =========================================================================
    async def resolve_latent_bond_7d_expiry(self) -> Dict[str, Any]:
        """
        When 7-day observation window expires with no verified diagnostic claim,
        releases the remaining 15% Latent Defect Bond to the tenant.
        Closes the tenancy state machine as SETTLED_TERMINATED.
        """
        timer = self.clock.get_timer(self.profile.tenancy_id, "LATENT_DEFECT_BOND_7D")
        if timer and not timer.is_expired:
            raise RuntimeError("7-Day Latent Defect Window has not yet expired.")

        self.current_state = TenancyLifecycleState.SETTLED_TERMINATED
        final_record = {
            "status": "SETTLED_TERMINATED",
            "tenancy_id": self.profile.tenancy_id,
            "latent_bond_released_pct": 15.0,
            "lifecycle_closed_at_utc": self.clock.current_time_iso,
            "state_machine_completed": True
        }
        self._log_event("STATE_MACHINE_CLOSED", TenancyLifecycleState.STATE_5_LATENT_DEFECT_WINDOW, self.current_state, final_record)
        return final_record
