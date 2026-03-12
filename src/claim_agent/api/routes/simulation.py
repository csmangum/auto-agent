"""Simulation API routes: role metadata for the role simulation feature."""

from fastapi import APIRouter

router = APIRouter(tags=["simulation"])


SIMULATION_ROLES = [
    {
        "id": "adjuster",
        "label": "Adjuster",
        "description": "Internal claims adjuster with full system access",
        "capabilities": [
            "Full claim lifecycle management",
            "Approve/reject claims",
            "Assign claims to adjusters",
            "View audit logs and workflows",
            "Access SIU information",
        ],
    },
    {
        "id": "customer",
        "label": "Customer",
        "description": "Policyholder or claimant filing and tracking claims",
        "capabilities": [
            "File new insurance claims",
            "Track claim status and timeline",
            "Respond to follow-up messages",
            "File disputes on settled claims",
            "View settlement offers and denial letters",
        ],
    },
    {
        "id": "repair_shop",
        "label": "Repair Shop",
        "description": "Body shop managing vehicle repairs and supplements",
        "capabilities": [
            "View assigned repair jobs",
            "Submit supplemental damage reports",
            "Respond to follow-up messages",
            "View repair authorizations and estimates",
            "Track parts and labor details",
        ],
    },
    {
        "id": "third_party",
        "label": "Third Party",
        "description": "Other insurance company or third-party claimant",
        "capabilities": [
            "View subrogation demands",
            "Respond to liability determinations",
            "Submit third-party claims",
            "Provide counter-evidence",
            "Track cross-carrier communications",
        ],
    },
]


@router.get("/simulation/roles")
def get_simulation_roles():
    """Return available simulation roles with metadata and capabilities."""
    return {"roles": SIMULATION_ROLES}
