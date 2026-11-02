"""Role -> permission map. Enforced by the API; the UI only uses it to shape navigation."""

from app.models import Role

C, S, Q = Role.care_coordinator, Role.support_engineer, Role.qa_engineer

PERMISSIONS: dict[str, set[Role]] = {
    "fleet:read": {C, S, Q},
    "alerts:read": {C, S, Q},
    "alerts:handle": {C, S},          # acknowledge / resolve
    "devices:read": {C, S, Q},
    "devices:command": {S, Q},        # resync clock, reboot, sync schedule, simulate roll replacement
    "devices:schedule": {S},
    "telemetry:read": {S, Q},
    "tickets:read": {C, S, Q},
    "tickets:create": {C, S, Q},
    "tickets:manage": {S},
    "faults:manage": {Q},
    "audit:read": {S, Q},
}


def permissions_for(role: Role) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)


def has_permission(role: Role, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())
