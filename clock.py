# Provenance: Derived from docs/state_machine.md § 3 (Programmed Timers and Windows) on 2026-10-04
"""
NEXUS Deterministic Clock and Timer Management.
Provides exact wall-clock tracking and virtual fast-forward capabilities for protocol timers:
- 72h Grace Period (e-NACH bounce)
- 24h Notice of Understanding (passive consent)
- 48h Unilateral Exit Timer (landlord ghosting)
- 7-Day Latent Defect Window
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Callable, List
from pydantic import BaseModel, Field


class ProtocolTimer(BaseModel):
    timer_id: str
    tenancy_id: str
    timer_name: str
    duration_hours: float
    started_at: datetime
    expires_at: datetime
    is_active: bool = True
    is_cancelled: bool = False
    is_expired: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VirtualClock:
    """Deterministic clock allowing precise temporal simulation and real-time execution."""
    
    def __init__(self, start_time: Optional[datetime] = None):
        self._current_time = start_time or datetime.now(timezone.utc)
        self._timers: Dict[str, ProtocolTimer] = {}

    @property
    def current_time(self) -> datetime:
        return self._current_time

    @property
    def current_time_iso(self) -> str:
        return self._current_time.isoformat()

    def advance_hours(self, hours: float) -> List[ProtocolTimer]:
        """Fast-forwards clock by given hours and returns newly expired timers."""
        target_time = self._current_time + timedelta(hours=hours)
        return self.advance_to(target_time)

    def advance_days(self, days: float) -> List[ProtocolTimer]:
        """Fast-forwards clock by given days and returns newly expired timers."""
        return self.advance_hours(days * 24.0)

    def advance_to(self, target_time: datetime) -> List[ProtocolTimer]:
        """Advances clock to specific timestamp, triggering any timers due."""
        if target_time < self._current_time:
            raise ValueError(f"Cannot rewind clock from {self._current_time} to {target_time}")
        
        self._current_time = target_time
        expired = []
        for timer in self._timers.values():
            if timer.is_active and not timer.is_cancelled and not timer.is_expired:
                if self._current_time >= timer.expires_at:
                    timer.is_expired = True
                    timer.is_active = False
                    expired.append(timer)
        return expired

    def arm_timer(self, tenancy_id: str, timer_name: str, duration_hours: float, metadata: Optional[Dict[str, Any]] = None) -> ProtocolTimer:
        """Arms a new statutory or contractual timer."""
        timer_id = f"TIMER_{tenancy_id}_{timer_name}_{int(self._current_time.timestamp())}"
        expires_at = self._current_time + timedelta(hours=duration_hours)
        timer = ProtocolTimer(
            timer_id=timer_id,
            tenancy_id=tenancy_id,
            timer_name=timer_name,
            duration_hours=duration_hours,
            started_at=self._current_time,
            expires_at=expires_at,
            metadata=metadata or {}
        )
        self._timers[timer_id] = timer
        return timer

    def cancel_timer(self, timer_id: str) -> Optional[ProtocolTimer]:
        """Cancels an active timer (e.g. landlord responds before 24h passive window expires)."""
        timer = self._timers.get(timer_id)
        if timer and timer.is_active:
            timer.is_active = False
            timer.is_cancelled = True
            return timer
        return None

    def get_active_timer(self, tenancy_id: str, timer_name: str) -> Optional[ProtocolTimer]:
        for timer in self._timers.values():
            if timer.tenancy_id == tenancy_id and timer.timer_name == timer_name and timer.is_active:
                return timer
        return None

    def get_timer(self, tenancy_id: str, timer_name: str) -> Optional[ProtocolTimer]:
        for timer in reversed(list(self._timers.values())):
            if timer.tenancy_id == tenancy_id and timer.timer_name == timer_name:
                return timer
        return None

    def check_expired_timers(self) -> List[ProtocolTimer]:
        expired = []
        for timer in self._timers.values():
            if timer.is_active and not timer.is_cancelled and not timer.is_expired:
                if self._current_time >= timer.expires_at:
                    timer.is_expired = True
                    timer.is_active = False
                    expired.append(timer)
        return expired
