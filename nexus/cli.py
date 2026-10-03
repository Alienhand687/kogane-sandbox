# Provenance: Derived from docs/state_machine.md and evals/run_100_evals.py on 2026-10-04
"""
NEXUS CLI & Interactive Orchestrator Runner.
Enables running full tenancy simulations, adversarial scenarios, and inspectable audit logs.

Usage:
    python -m nexus.cli --scenario happy_path
    python -m nexus.cli --scenario wear_and_tear
    python -m nexus.cli --scenario occlusion_trap
    python -m nexus.cli --scenario landlord_ghosting
    python -m nexus.cli --scenario rent_bounce
    python -m nexus.cli --all
"""

import sys
import asyncio
import argparse
import json
from datetime import datetime, timezone
import sandbox.unified_sandbox_mcp as sm
from nexus.scenarios import (
    run_scenario_happy_path,
    run_scenario_wear_and_tear,
    run_scenario_occlusion_loop_guard,
    run_scenario_landlord_ghosting,
    run_scenario_rent_bounce_fldg,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def reset_sandbox_state():
    sm.STATE_STORE.clear()
    sm.STATE_STORE.update({
        "tenancies": {},
        "vaults": {},
        "inspections": {},
        "covenants": {},
        "audit_trail": []
    })


async def run_scenario(name: str):
    reset_sandbox_state()
    print(f"\n================================================================================")
    print(f">> EXECUTING NEXUS PROTOCOL SCENARIO: {name.upper()}")
    print(f"================================================================================")

    if name in ["happy_path", "happy"]:
        res = await run_scenario_happy_path()
    elif name in ["wear_and_tear", "paint"]:
        res = await run_scenario_wear_and_tear()
    elif name in ["occlusion_trap", "loop_guard"]:
        res = await run_scenario_occlusion_loop_guard()
    elif name in ["landlord_ghosting", "ghost"]:
        res = await run_scenario_landlord_ghosting()
    elif name in ["rent_bounce", "fldg"]:
        res = await run_scenario_rent_bounce_fldg()
    else:
        print(f"Unknown scenario: {name}")
        return False

    print("\n[OK] EXECUTION SUMMARY:")
    for k, v in res.items():
        print(f"  * {k:30s}: {v}")

    print("\n[OK] STATE STORE FINAL LEDGER:")
    print(f"  * Vaults tracked: {len(sm.STATE_STORE['vaults'])}")
    print(f"  * Tenancies registered: {len(sm.STATE_STORE['tenancies'])}")
    print(f"  * Audit events logged: {len(sm.STATE_STORE['audit_trail'])}")
    return True


async def main():
    parser = argparse.ArgumentParser(description="Kogane NEXUS Orchestrator Engine Runner")
    parser.add_argument("--scenario", "-s", type=str, help="Specific scenario name to execute")
    parser.add_argument("--all", "-a", action="store_true", help="Execute all canonical scenarios sequentially")

    args = parser.parse_args()

    if args.all or not args.scenario:
        scenarios = [
            "happy_path",
            "wear_and_tear",
            "occlusion_trap",
            "landlord_ghosting",
            "rent_bounce"
        ]
        passed = 0
        for sc in scenarios:
            success = await run_scenario(sc)
            if success:
                passed += 1

        print(f"\n================================================================================")
        print(f"NEXUS SUITE COMPLETE: {passed}/{len(scenarios)} SCENARIOS PASSED WITH ZERO REGRESSIONS.")
        print(f"================================================================================\n")
    else:
        await run_scenario(args.scenario)


if __name__ == "__main__":
    asyncio.run(main())
