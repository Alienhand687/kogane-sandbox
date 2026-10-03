# Provenance: Derived from docs/state_machine.md, evals/test_condition_vectors.py, and decisions/LOCKED.md on 2026-10-04
"""
Canonical Scenario Suites for NEXUS Orchestrator Execution and Hackathon Pitch Demos.
"""

from typing import Dict, Any
from nexus.models import TenancyProfile, TenantScanStatus
from nexus.clock import VirtualClock
from nexus.orchestrator import NexusOrchestrator, TenancyLifecycleState


async def run_scenario_happy_path(verbose: bool = True) -> Dict[str, Any]:
    """
    Scenario 1: Happy Path Full Tenancy.
    Onboarding -> Baseline Capture -> Active Tenancy (Yield Accrual) ->
    T-24h Clean Exit Sweep -> T-0 Handover QR -> 85% Release ->
    7-Day Latent Window Expiry -> 15% Release -> Settled.
    """
    clock = VirtualClock()
    profile = TenancyProfile(
        tenancy_id="TEN-HAPPY-01",
        tenant_id="TENANT-RAHUL-01",
        landlord_id="LANDLORD-SURESH-01",
        property_pincode="560001",
        deposit_amount_inr=200000.0,
        monthly_rent_inr=35000.0,
        lease_duration_months=11
    )
    nexus = NexusOrchestrator(profile, clock)

    # State 0: Onboarding
    v_res = await nexus.run_state_0_onboarding()

    # State 1: Baseline
    b_res = await nexus.run_state_1_baseline_capture()

    # State 2: Active Tenancy (Simulate 11 months of daily sweeps)
    clock.advance_days(330)
    sweep_res = await nexus.execute_daily_treps_sweep()

    # State 3: Condition Freeze (T-24h)
    d_res = await nexus.trigger_move_out_inspection()
    # Clean exit sweep (eval_clean_sweep in fixtures, or empty anomalies)
    pkg = await nexus.execute_move_out_analysis(
        exit_mesh_id="MESH_EXIT_CLEAN_01",
        duration_months=11,
        tenant_scan_status=TenantScanStatus.SKIPPED
    )

    # State 4: T-0 Handover QR Scan
    payout_t0 = await nexus.execute_t0_possession_payout(auth_signal="NONCE_T0_VALID_891723")

    # State 5: Latent Defect Window (Advance 7 days)
    clock.advance_days(7.1)
    final_res = await nexus.resolve_latent_bond_7d_expiry()

    return {
        "scenario": "HAPPY_PATH_11M",
        "final_state": nexus.current_state.value,
        "vault_id": nexus.vault_id,
        "initial_deposit_inr": profile.deposit_amount_inr,
        "immediate_payout_inr": payout_t0.get("tenant_immediate_payout_inr"),
        "latent_bond_inr": payout_t0.get("latent_defect_bond_hold_inr"),
        "audit_event_count": len(nexus.audit_log)
    }


async def run_scenario_wear_and_tear(verbose: bool = True) -> Dict[str, Any]:
    """
    Scenario 2: Wall Paint Wear & Tear under CPWD statutory curves with Landlord Claim Dismissal.
    Landlord demands Rs 18,000 for stained walls.
    Duration is 26 months (exceeding CPWD wall paint lifespan of 24 months).
    Final allowable deduction evaluates strictly to Rs 0.00.
    """
    clock = VirtualClock()
    profile = TenancyProfile(
        tenancy_id="eval_paint_wear",
        tenant_id="TENANT-ANANYA-02",
        landlord_id="LANDLORD-VIKRAM-02",
        property_pincode="560001",
        deposit_amount_inr=150000.0,
        monthly_rent_inr=25000.0,
        lease_duration_months=26
    )
    nexus = NexusOrchestrator(profile, clock)

    await nexus.run_state_0_onboarding()
    await nexus.run_state_1_baseline_capture()

    # Move-out inspection at 26 months
    await nexus.trigger_move_out_inspection()
    pkg = await nexus.execute_move_out_analysis(
        exit_mesh_id="eval_paint_wear",
        duration_months=26,
        tenant_scan_status=TenantScanStatus.SKIPPED,
        landlord_claim_text="Tenant left walls completely stained. Deduct full repainting Rs 18,000 immediately."
    )

    # T-0 QR Handover
    payout_t0 = await nexus.execute_t0_possession_payout(auth_signal="NONCE_T0_VALID_PAINT_01")

    # Advance 7 days
    clock.advance_days(7.01)
    await nexus.resolve_latent_bond_7d_expiry()

    return {
        "scenario": "WEAR_AND_TEAR_LANDLORD_INFLATION",
        "final_state": nexus.current_state.value,
        "total_allowable_deduction_inr": pkg.total_allowable_deduction_inr,
        "statutory_amortization": "PAINT_WEAR_DEPRECIATED_ZERO (26m >= 24m CPWD lifespan)",
        "audit_event_count": len(nexus.audit_log)
    }


async def run_scenario_occlusion_loop_guard(verbose: bool = True) -> Dict[str, Any]:
    """
    Scenario 3: Adversarial Occlusion Trap and Loop Guard.
    First pass occluded -> Supervisory rescan dispatched -> Second pass still occluded ->
    Trips loop guard and safely escalates to HITL arbitration.
    """
    clock = VirtualClock()
    profile = TenancyProfile(
        tenancy_id="eval_occlusion_trap",
        tenant_id="TENANT-SID-03",
        landlord_id="LANDLORD-MEHTA-03",
        property_pincode="560001",
        deposit_amount_inr=180000.0,
        monthly_rent_inr=30000.0,
        lease_duration_months=12
    )
    nexus = NexusOrchestrator(profile, clock)

    await nexus.run_state_0_onboarding()
    await nexus.run_state_1_baseline_capture()

    # First inspection pass: trips occlusion
    await nexus.trigger_move_out_inspection()
    pkg1 = await nexus.execute_move_out_analysis(
        exit_mesh_id="eval_occlusion_trap",
        duration_months=12
    )
    assert pkg1.inspection_status == "DISPATCH_RESCAN"
    assert nexus.rescan_count == 1

    # Second inspection pass: persistent occlusion trips loop guard
    pkg2 = await nexus.execute_move_out_analysis(
        exit_mesh_id="eval_occlusion_trap",
        duration_months=12
    )
    assert pkg2.inspection_status == "HITL"
    assert "OCCLUSION_LOOP_GUARD_TRIPPED" in pkg2.reason_codes
    assert nexus.current_state == TenancyLifecycleState.HITL_ARBITRATION

    return {
        "scenario": "OCCLUSION_LOOP_GUARD",
        "final_state": nexus.current_state.value,
        "rescan_attempts": nexus.rescan_count,
        "loop_guard_status": "TRIPPED_SAFELY_TO_HITL",
        "audit_event_count": len(nexus.audit_log)
    }


async def run_scenario_landlord_ghosting(verbose: bool = True) -> Dict[str, Any]:
    """
    Scenario 4: Landlord Ghosting at T-0 Handover.
    Landlord refuses to scan QR -> Tenant drops keys at lockbox ->
    48-Hour Unilateral Exit Timer expires -> Undisputed deposit auto-releases to tenant.
    """
    clock = VirtualClock()
    profile = TenancyProfile(
        tenancy_id="TEN-GHOST-04",
        tenant_id="TENANT-PRIYA-04",
        landlord_id="LANDLORD-GHOST-04",
        property_pincode="560001",
        deposit_amount_inr=200000.0,
        monthly_rent_inr=32000.0,
        lease_duration_months=11
    )
    nexus = NexusOrchestrator(profile, clock)

    await nexus.run_state_0_onboarding()
    await nexus.run_state_1_baseline_capture()
    await nexus.trigger_move_out_inspection()
    await nexus.execute_move_out_analysis(
        exit_mesh_id="MESH_CLEAN_GHOST",
        duration_months=11
    )

    # Landlord ghosts at T-0: Arm 48h unilateral exit timer
    timer = await nexus.handle_landlord_ghosting_unilateral_exit()
    assert timer.duration_hours == 48.0

    # Advance clock past 48 hours uncontested
    expired_timers = clock.advance_hours(48.5)
    assert any(t.timer_name == "UNILATERAL_EXIT_48H" for t in expired_timers)

    # Auto-resolve payout
    payout = await nexus.resolve_unilateral_exit_expiry()
    assert payout.get("status") == "SETTLED_TERMINATED"

    return {
        "scenario": "LANDLORD_GHOSTING_48H",
        "final_state": nexus.current_state.value,
        "timer_name": "UNILATERAL_EXIT_48H",
        "unilateral_payout_status": payout.get("status"),
        "tenant_payout_inr": payout.get("tenant_immediate_payout_inr"),
        "audit_event_count": len(nexus.audit_log)
    }


async def run_scenario_rent_bounce_fldg(verbose: bool = True) -> Dict[str, Any]:
    """
    Scenario 5: Rent Mandate Bounce & 72-Hour Grace FLDG Auto-Draw.
    e-NACH auto-debit bounces -> 72h Grace Period arms ->
    Clock advances 72h without payment -> FLDG rent automatically drawn from deposit principal.
    """
    clock = VirtualClock()
    profile = TenancyProfile(
        tenancy_id="TEN-RENT-05",
        tenant_id="TENANT-KARAN-05",
        landlord_id="LANDLORD-SHARMA-05",
        property_pincode="560001",
        deposit_amount_inr=200000.0,
        monthly_rent_inr=30000.0,
        lease_duration_months=11
    )
    nexus = NexusOrchestrator(profile, clock)

    await nexus.run_state_0_onboarding()
    await nexus.run_state_1_baseline_capture()

    # Rent debit bounce
    grace_timer = await nexus.handle_rent_mandate_bounce()
    assert grace_timer.duration_hours == 72.0

    # Fast forward clock 72 hours
    expired_timers = clock.advance_hours(72.5)
    assert any(t.timer_name == "RENT_GRACE_72H" for t in expired_timers)

    # Resolve FLDG deduction
    fldg_res = await nexus.resolve_rent_grace_expiry()
    assert fldg_res.get("status") in ["FACTORING_REIMBURSED", "FLDG_LIQUIDATED"]
    assert fldg_res.get("liquidated_amount_inr") == 30000.0

    return {
        "scenario": "RENT_BOUNCE_72H_FLDG",
        "final_state": nexus.current_state.value,
        "rent_deducted_inr": fldg_res.get("liquidated_amount_inr"),
        "settlement_utr": fldg_res.get("nbfc_settlement_utr"),
        "audit_event_count": len(nexus.audit_log)
    }
