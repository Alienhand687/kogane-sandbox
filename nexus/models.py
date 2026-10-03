# Provenance: Derived from docs/state_machine.md, context/agents_and_tools.md, and decisions/LOCKED.md on 2026-10-04
"""
NEXUS Orchestrator Data Contracts and State Taxonomies.
Defines the state machine enums, event schemas, and payload models for Kogane's Level 4 workflow engine.
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field
from datetime import datetime


class TenancyLifecycleState(str, Enum):
    STATE_0_ONBOARDING = "STATE_0_ONBOARDING"
    STATE_1_BASELINE_CAPTURE = "STATE_1_BASELINE_CAPTURE"
    STATE_2_ACTIVE_TENANCY = "STATE_2_ACTIVE_TENANCY"
    STATE_3_CONDITION_FREEZE = "STATE_3_CONDITION_FREEZE"
    STATE_4_POSSESSION_SURRENDER = "STATE_4_POSSESSION_SURRENDER"
    STATE_5_LATENT_DEFECT_WINDOW = "STATE_5_LATENT_DEFECT_WINDOW"
    SETTLED_TERMINATED = "SETTLED_TERMINATED"
    HITL_ARBITRATION = "HITL_ARBITRATION"
    LITIGATION_TERMINATED = "LITIGATION_TERMINATED"


class InspectionEvent(str, Enum):
    MOVE_OUT_AUDIT = "MOVE_OUT_AUDIT"
    SUPERVISORY_RESCAN = "SUPERVISORY_RESCAN"


class TenantScanStatus(str, Enum):
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    PIPELINE_ERROR = "PIPELINE_ERROR"


class LandlordDecision(str, Enum):
    APPROVE = "APPROVE"
    DISPUTE = "DISPUTE"
    SILENCE_24H = "SILENCE_24H"


class TenancyProfile(BaseModel):
    tenancy_id: str
    tenant_id: str
    landlord_id: str
    property_pincode: str
    latitude: float = 12.9716
    longitude: float = 77.5946
    deposit_amount_inr: float
    monthly_rent_inr: float
    lease_duration_months: int = 11
    trustee_code: str = "AXIS_TRUSTEE"
    custody_bank: str = "ICICI"


class DeductionLineItem(BaseModel):
    surface_category: str
    zone: str = "LIVING_ROOM"
    raw_repair_cost_inr: float
    clamped_base_cost_inr: float
    allowable_deduction_inr: float
    statutory_rationale: str
    excess_over_sor_inr: float = 0.0


class DeductionPackage(BaseModel):
    tenancy_id: str
    inspection_status: str
    total_allowable_deduction_inr: Optional[float] = None
    delta_vector: Optional[List[Dict[str, Any]]] = None
    reason_codes: List[str] = Field(default_factory=list)
    next_recommended_state: str
    hitl_brief: Optional[Dict[str, Any]] = None


class WorkflowEventRecord(BaseModel):
    event_id: str
    timestamp_utc: str
    event_type: str
    source_agent_or_actor: str
    from_state: str
    to_state: str
    payload: Dict[str, Any]
    status: str
