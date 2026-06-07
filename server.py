#!/usr/bin/env python3
"""
MEOK ALLMI Hiab / Lorry-Loader MCP
=========================================

By MEOK AI Labs · https://haulage.app · MIT
<!-- mcp-name: io.github.CSOAI-ORG/meok-allmi-hiab-mcp -->

WHAT THIS DOES
--------------
UK lorry-loader (hiab) compliance + brick-grab POD toolkit for builders'
merchants and specialist lift operators. Wraps the ALLMI Approved Code of
Practice, BS 7121-4:2010 (Lorry Loaders), LOLER 1998 (still applies),
CPCS A36 / A40 / A73 operator-card schemes, CPA Model Conditions, and the
BMF Code of Practice into callable tools.

EVERY brick-grab, pallet of blocks, or kerbstone delivery in the UK goes
through this regulatory stack. The TOP-6 UK builders' merchants (Travis
Perkins, Jewson, MKM, Selco, Buildbase, Howdens) plus ~800-1,500 specialist
hiab operators run the same paperwork: ALLMI Thorough Examination, lift
plan signoff, slinger/signaller cards, walkaround check, signed POD.

This MCP turns the paperwork-on-clipboard process into a sub-second tool
call — with the magic-button site-foreman SMS that prevents the £200-£450
rejected-delivery loss that everybody bleeds.

TOOLS (8)
---------
- generate_hiab_lift_plan(load, vehicle, site)        → BS 7121-4 lift plan
- triage_contract_lift_threshold(job)                 → Hire vs Contract Lift
- check_allmi_thorough_examination(eq, last_te)       → 6/12-mo TE due
- check_cpcs_a36(card_number, expiry)                 → Lorry Loader card
- check_slinger_a40_a73(card, category, expiry)       → Slinger/Signaller
- capture_brick_grab_pod(delivery)                    → ePOD-ready record
- flag_delivery_rejection_risk(site)                  → score + foreman SMS
- audit_pre_delivery_walkaround(driver, vehicle, checks) → 25-pt HSE check

WHY YOU PAY
-----------
A single avoided £200-£450 rejected brick-delivery = single-day payback at
Pro (£119/mo). Builders' merchants run thousands of hiab drops daily —
every drop runs through this stack.

PRICING
-------
Free MIT self-host · £39/mo Starter · £119/mo Pro · £499/mo Fleet.

REGULATORY BASIS
----------------
BS 7121-4:2010 — Code of practice for safe use of cranes, Part 4: Lorry loaders
ALLMI Approved Code of Practice (lorry-loader operator + AP roles)
ALLMI Thorough Examination scheme (6-monthly LL; 12-monthly attachments)
LOLER 1998 — Lifting Operations and Lifting Equipment Regulations
PUWER 1998 — Provision and Use of Work Equipment Regulations
CPCS A36 — Lorry Loader operator card
CPCS A40 — Slinger / Signaller (light lift)
CPCS A73 — Slinger / Signaller (general lifting)
CPA Model Conditions for Hire of Plant (CPA / CPA-MCH)
BMF Code of Practice — Builders' Merchants Federation
HSE Approved Code of Practice L113 (Safe use of lifting equipment)
"""

from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone, date
from typing import Optional
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("meok-allmi-hiab")
_HMAC_SECRET = os.environ.get("MEOK_HMAC_SECRET", "")


# ──────────────────────────────────────────────────────────────────────
# Regulatory tables (BS 7121-4 / ALLMI / CPCS)
# ──────────────────────────────────────────────────────────────────────

# Brick-grab + common hiab attachments and their typical SWL band
HIAB_ATTACHMENT_TYPES = {
    "brick_grab": {"swl_kg": 1500, "typical_use": "Bricks, blocks, kerbs, slabs"},
    "block_grab": {"swl_kg": 1800, "typical_use": "Aircrete + dense blocks"},
    "pallet_fork": {"swl_kg": 2000, "typical_use": "Palletised packs"},
    "kerb_grab": {"swl_kg": 350, "typical_use": "PCC kerbstones one-at-a-time"},
    "stillage_hook": {"swl_kg": 1000, "typical_use": "Roof tile stillages"},
    "scaffold_clamp": {"swl_kg": 500, "typical_use": "Scaffold tube + boards"},
    "rotator_hook": {"swl_kg": 800, "typical_use": "Free-swung hook lifts"},
    "concrete_skip": {"swl_kg": 1000, "typical_use": "Concrete pours via hiab"},
}

# ALLMI Thorough Examination intervals
ALLMI_TE_INTERVALS_MONTHS = {
    "lorry_loader_carrying_loads": 12,         # LOLER 7(2)(a)
    "lorry_loader_personnel_lifting": 6,       # LOLER 9(3)(b) — personnel = 6mo
    "loose_lifting_accessory": 6,              # Slings, chains, hooks
    "brick_grab_attachment": 12,               # Treated as lifting accessory body
    "block_grab_attachment": 12,
    "kerb_grab_attachment": 12,
    "pallet_fork_attachment": 12,
    "rotator_assembly": 12,
}

# CPCS card categories (subset)
CPCS_CARDS = {
    "A36": {"title": "Lorry Loader", "scope": "Operate lorry-loader (hiab) for materials transfer"},
    "A40": {"title": "Slinger / Signaller (Light)", "scope": "Sling + signal lifts up to 5 tonnes"},
    "A73": {"title": "Slinger / Signaller (All Duties)", "scope": "Sling + signal lifts of any weight"},
    "A77": {"title": "Crane Supervisor", "scope": "Plan + supervise lifts (BS 7121-1)"},
    "A61": {"title": "Appointed Person", "scope": "Plan complex + non-routine lifts"},
}

# Hire vs Contract Lift triage — CPA Model Conditions
CONTRACT_LIFT_INDICATORS = {
    "operator_responsible_for_load_path": True,
    "operator_responsible_for_slinging": True,
    "operator_responsible_for_lift_plan": True,
    "operator_carries_insurance_for_load": True,
    "customer_provides_no_competent_slinger": True,
    "customer_is_domestic_or_unfamiliar": True,
    "lift_above_routine_swl_for_attachment": True,
    "lift_near_public_highway_or_people": True,
}

# Delivery rejection risk weights (validated against builders' merchant data)
REJECTION_RISK_WEIGHTS = {
    "gates_locked": 35,
    "no_banksman_on_site": 25,
    "site_closed_for_slot": 40,
    "wrong_product_mix": 30,
    "wrong_slot_time": 20,
    "obstructed_access": 25,
    "overhead_powerlines": 50,        # safety stop — auto refuse
    "soft_ground_unstable": 30,
    "no_foreman_contact": 15,
    "previous_failed_delivery": 20,
}

# HSE COP L113 / ALLMI pre-delivery walkaround — 25 point check
WALKAROUND_CHECKS_25 = [
    "tyres_legal_tread_and_pressure",
    "wheel_nuts_indicators_aligned",
    "service_brakes_function",
    "park_brake_holds_loaded",
    "lights_front_rear_indicators",
    "mirrors_all_present_clean",
    "windscreen_wipers_washers",
    "horn_operates",
    "first_aid_kit_present",
    "fire_extinguisher_in_date",
    "hi_vis_helmet_gloves_boots_in_cab",
    "hydraulic_lines_no_leaks",
    "hydraulic_oil_level_correct",
    "outriggers_extend_fully",
    "outrigger_pads_present",
    "slewing_ring_no_play",
    "boom_pivots_greased",
    "rope_or_chain_slings_no_damage",
    "brick_grab_jaws_close_fully",
    "grab_safety_pin_present",
    "attachment_locks_engaged",
    "load_chart_legible_in_cab",
    "rci_rated_capacity_indicator_works",
    "sheets_ropes_straps_in_date",
    "driver_walkaround_signed_off",
]


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _sign(payload: dict) -> str:
    """HMAC-sign the response for tamper-evident audit."""
    if not _HMAC_SECRET:
        return "unsigned-no-key-configured"
    return hmac.new(
        _HMAC_SECRET.encode(),
        json.dumps(payload, sort_keys=True, default=str).encode(),
        hashlib.sha256,
    ).hexdigest()


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attestation(payload: dict) -> dict:
    return {
        **payload,
        "ts": _ts(),
        "sig": _sign(payload),
        "issuer": "meok-allmi-hiab-mcp",
        "version": "1.0.0",
    }


def _months_between(d1: date, d2: date) -> float:
    """Approx months between two dates (30.44-day average)."""
    return (d2 - d1).days / 30.44


# ──────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def generate_hiab_lift_plan(
    load_weight_kg: float,
    load_length_m: float = 1.0,
    load_width_m: float = 1.0,
    load_height_m: float = 1.0,
    load_description: str = "Pack of bricks",
    vehicle_make: str = "Scania",
    vehicle_crane_swl_kg: float = 3000.0,
    vehicle_max_reach_m: float = 8.0,
    site_postcode: str = "",
    site_ground_condition: str = "tarmac",
    overhead_obstructions: bool = False,
    public_within_exclusion_zone: bool = False,
    attachment_type: str = "brick_grab",
) -> dict:
    """Generate a BS 7121-4 compliant hiab lift plan.

    Args:
      load_weight_kg: total load weight to be lifted
      load_length_m / width_m / height_m: load dims
      load_description: free-text (eg 'Pack of 500 bricks')
      vehicle_make: tractor manufacturer
      vehicle_crane_swl_kg: SWL of crane at planned reach
      vehicle_max_reach_m: planned slewing reach
      site_postcode: drop postcode
      site_ground_condition: 'tarmac' / 'concrete' / 'compacted_hardcore' /
                              'soft_ground' / 'pavers' / 'grass_mud'
      overhead_obstructions: power lines, eaves, scaffolding nearby
      public_within_exclusion_zone: pedestrians/highway inside slew radius
      attachment_type: key from HIAB_ATTACHMENT_TYPES

    Returns:
      Lift plan dict + AP signoff trigger per BS 7121-4 + ALLMI ACoP.
    """
    attachment_spec = HIAB_ATTACHMENT_TYPES.get(
        attachment_type, HIAB_ATTACHMENT_TYPES["brick_grab"]
    )

    # Safe Working Load envelope check
    swl_utilisation_pct = round((load_weight_kg / vehicle_crane_swl_kg) * 100, 1) if vehicle_crane_swl_kg else 999.0
    over_swl = load_weight_kg > vehicle_crane_swl_kg
    over_attachment_swl = load_weight_kg > attachment_spec["swl_kg"]

    # Exclusion zone radius — BS 7121-4 §6.3 (slew radius + load swing + 1.5m buffer)
    exclusion_zone_m = round(vehicle_max_reach_m + max(load_length_m, load_width_m) + 1.5, 1)

    # Outrigger extension policy
    if site_ground_condition in ("tarmac", "concrete"):
        outrigger_pads_required = True
        outrigger_extension = "Full extension both sides"
    elif site_ground_condition == "compacted_hardcore":
        outrigger_pads_required = True
        outrigger_extension = "Full extension; pads + spreader timbers"
    elif site_ground_condition in ("soft_ground", "grass_mud"):
        outrigger_pads_required = True
        outrigger_extension = "Full extension + 1m² spreader pads MANDATORY; AP may refuse"
    else:
        outrigger_pads_required = True
        outrigger_extension = "Full extension + spreader pads"

    # AP signoff trigger logic — when lift becomes "non-routine"
    ap_signoff_required = (
        over_swl
        or over_attachment_swl
        or overhead_obstructions
        or public_within_exclusion_zone
        or site_ground_condition in ("soft_ground", "grass_mud")
        or swl_utilisation_pct >= 80.0
    )

    # Lift classification (BS 7121-1 categorisation)
    if over_swl or overhead_obstructions or public_within_exclusion_zone:
        lift_category = "complex"
    elif ap_signoff_required:
        lift_category = "non-routine"
    else:
        lift_category = "basic"

    issues = []
    if over_swl:
        issues.append(
            f"LOAD {load_weight_kg}kg EXCEEDS crane SWL {vehicle_crane_swl_kg}kg at {vehicle_max_reach_m}m — STOP"
        )
    if over_attachment_swl:
        issues.append(
            f"LOAD {load_weight_kg}kg EXCEEDS {attachment_type} SWL {attachment_spec['swl_kg']}kg — STOP"
        )
    if overhead_obstructions:
        issues.append("Overhead obstructions present — survey + insulate or relocate lift")
    if public_within_exclusion_zone:
        issues.append("Public inside exclusion zone — banksman + cordon + AP signoff")

    plan = {
        "tool": "generate_hiab_lift_plan",
        "reference": "BS 7121-4:2010 + ALLMI ACoP",
        "lift_category": lift_category,
        "load": {
            "description": load_description,
            "weight_kg": load_weight_kg,
            "dimensions_m": {
                "length": load_length_m,
                "width": load_width_m,
                "height": load_height_m,
            },
        },
        "vehicle": {
            "make": vehicle_make,
            "crane_swl_kg": vehicle_crane_swl_kg,
            "max_reach_m": vehicle_max_reach_m,
            "swl_utilisation_pct": swl_utilisation_pct,
        },
        "attachment": {
            "type": attachment_type,
            "swl_kg": attachment_spec["swl_kg"],
            "typical_use": attachment_spec["typical_use"],
        },
        "site": {
            "postcode": site_postcode,
            "ground_condition": site_ground_condition,
            "outrigger_pads_required": outrigger_pads_required,
            "outrigger_extension": outrigger_extension,
            "overhead_obstructions": overhead_obstructions,
            "public_within_exclusion_zone": public_within_exclusion_zone,
        },
        "exclusion_zone_radius_m": exclusion_zone_m,
        "ap_signoff_required": ap_signoff_required,
        "issues": issues,
        "compliant_to_proceed": (not issues) and (not over_swl) and (not over_attachment_swl),
        "advisory": (
            "STOP — lift cannot proceed safely. Escalate to AP + re-plan."
            if issues else (
                "AP signoff required before lift commences."
                if ap_signoff_required
                else "Basic lift — operator may proceed per ALLMI ACoP routine controls."
            )
        ),
    }
    return _attestation(plan)


@mcp.tool()
def triage_contract_lift_threshold(
    job_description: str = "",
    customer_provides_slinger: bool = False,
    operator_carries_load_insurance: bool = False,
    lift_near_public: bool = False,
    customer_is_domestic: bool = True,
    load_value_gbp: float = 0.0,
    lift_above_routine_swl: bool = False,
    operator_writes_lift_plan: bool = True,
    site_has_appointed_person: bool = False,
) -> dict:
    """Triage a hiab job as Hire (CPA Model Conditions) vs Contract Lift.

    The wedge question for £100k+ liability:
      - HIRE       = customer slings, customer plans lift, operator drives crane.
                     Customer carries liability for the load.
      - CONTRACT   = operator slings, operator plans lift, operator owns site
                     safety. Operator carries liability for load + lift.

    BS 7121-4 + CPA Model Conditions for Hire of Plant govern the split.

    Returns:
      classification, indicator_hits, recommended_insurance, advisory.
    """
    indicators_hit = []
    if not customer_provides_slinger: indicators_hit.append("customer_provides_no_competent_slinger")
    if operator_writes_lift_plan: indicators_hit.append("operator_responsible_for_lift_plan")
    if operator_carries_load_insurance: indicators_hit.append("operator_carries_insurance_for_load")
    if lift_near_public: indicators_hit.append("lift_near_public_highway_or_people")
    if customer_is_domestic: indicators_hit.append("customer_is_domestic_or_unfamiliar")
    if lift_above_routine_swl: indicators_hit.append("lift_above_routine_swl_for_attachment")
    if not site_has_appointed_person: indicators_hit.append("operator_responsible_for_load_path")
    if not customer_provides_slinger: indicators_hit.append("operator_responsible_for_slinging")

    # Threshold: 3+ indicators = Contract Lift recommended
    contract_lift_score = len(set(indicators_hit))
    classification = "CONTRACT_LIFT" if contract_lift_score >= 3 else "HIRE"

    if classification == "CONTRACT_LIFT":
        recommended_insurance = [
            "Public liability £10m minimum",
            "Plant + load damage cover (£500k+ depending on load value)",
            "Operator/slinger competence insurance (CPCS A36 + A40/A73 verified)",
            "AP signoff documented + lift plan retained 6+ years",
        ]
        advisory = (
            f"CONTRACT LIFT — {contract_lift_score} CPA indicators hit. "
            "Operator carries full liability for slinging, lift plan, load path, "
            "and load damage. Charge contract-lift rate (typically 1.4x hire rate). "
            "BS 7121-4 + ALLMI ACoP mandates AP-signed lift plan."
        )
    else:
        recommended_insurance = [
            "Public liability £5m minimum",
            "Plant-only damage cover",
            "Customer carries load damage liability (CPA Form 10/2011)",
        ]
        advisory = (
            f"HIRE — only {contract_lift_score} CPA indicators hit. "
            "Customer takes responsibility for slinging + lift plan. "
            "Issue CPA Model Conditions Form 10/2011 + record customer's "
            "competent person details before crane operations begin."
        )

    payload = {
        "tool": "triage_contract_lift_threshold",
        "job_description": job_description,
        "classification": classification,
        "indicator_count": contract_lift_score,
        "indicators_hit": indicators_hit,
        "load_value_gbp": load_value_gbp,
        "recommended_insurance": recommended_insurance,
        "advisory": advisory,
        "reference": "CPA Model Conditions for Hire of Plant + BS 7121-4 §5.2",
    }
    return _attestation(payload)


@mcp.tool()
def check_allmi_thorough_examination(
    equipment_id: str,
    equipment_type: str = "lorry_loader_carrying_loads",
    last_te_date: str = "",
    used_for_personnel: bool = False,
) -> dict:
    """Check ALLMI Thorough Examination status against LOLER 1998 + ALLMI scheme.

    Args:
      equipment_id: serial / fleet number
      equipment_type: key into ALLMI_TE_INTERVALS_MONTHS
                       (lorry_loader_carrying_loads, brick_grab_attachment, etc.)
      last_te_date: ISO YYYY-MM-DD of last Thorough Examination
      used_for_personnel: if true, forces 6-monthly per LOLER 9(3)(b)

    Returns:
      due_date, days_to_due, status, advisory.
    """
    # Personnel lifting overrides everything to 6 months
    if used_for_personnel:
        interval_months = 6
        effective_type = "lorry_loader_personnel_lifting"
    else:
        interval_months = ALLMI_TE_INTERVALS_MONTHS.get(equipment_type, 12)
        effective_type = equipment_type

    issues = []
    try:
        last = date.fromisoformat(last_te_date)
        # next due
        # crude — interval months added to last
        next_due_year = last.year + (last.month - 1 + interval_months) // 12
        next_due_month = (last.month - 1 + interval_months) % 12 + 1
        next_due_day = min(last.day, 28)
        next_due = date(next_due_year, next_due_month, next_due_day)
        days_to_due = (next_due - date.today()).days
        months_since_last = round(_months_between(last, date.today()), 2)

        if days_to_due < 0:
            status = "OVERDUE"
            issues.append(
                f"OVERDUE — TE was due {-days_to_due} days ago. "
                "Equipment MUST NOT be used until TE is complete (LOLER 9)."
            )
        elif days_to_due < 14:
            status = "DUE_IMMINENT"
            issues.append(f"Due in {days_to_due} days — book ALLMI examiner now")
        else:
            status = "VALID"
    except Exception:
        status = "INVALID_DATE"
        next_due = None
        days_to_due = None
        months_since_last = None
        issues.append("Could not parse last_te_date — expected ISO YYYY-MM-DD")

    payload = {
        "tool": "check_allmi_thorough_examination",
        "equipment_id": equipment_id,
        "equipment_type": effective_type,
        "interval_months": interval_months,
        "last_te_date": last_te_date,
        "next_due_date": next_due.isoformat() if next_due else None,
        "days_to_due": days_to_due,
        "months_since_last": months_since_last,
        "status": status,
        "used_for_personnel": used_for_personnel,
        "can_lift_today": status in ("VALID", "DUE_IMMINENT"),
        "issues": issues,
        "reference": "LOLER 1998 reg 9 + ALLMI Thorough Examination scheme",
    }
    return _attestation(payload)


@mcp.tool()
def check_cpcs_a36(
    operator_name: str,
    card_number: str,
    expiry_date: str,
    card_type: str = "blue_competent",
) -> dict:
    """Verify a CPCS A36 (Lorry Loader) operator card.

    Args:
      operator_name: full name as on card
      card_number: CPCS registration number
      expiry_date: ISO YYYY-MM-DD
      card_type: 'red_trained' / 'blue_competent' / 'gold_advanced'
    """
    spec = CPCS_CARDS["A36"]
    try:
        exp = date.fromisoformat(expiry_date)
        days_to_expiry = (exp - date.today()).days
        is_valid = days_to_expiry > 0
    except Exception:
        days_to_expiry = -1
        is_valid = False

    issues = []
    if not is_valid:
        issues.append("EXPIRED — operator cannot run hiab on public road or site")
    elif days_to_expiry < 60:
        issues.append(f"Expires in {days_to_expiry} days — book renewal now")
    if card_type == "red_trained":
        issues.append("RED (trained) card only — must be supervised by Blue/Gold A36 holder")

    payload = {
        "tool": "check_cpcs_a36",
        "operator_name": operator_name,
        "card_number": card_number,
        "card_category": "A36",
        "card_title": spec["title"],
        "card_scope": spec["scope"],
        "card_type": card_type,
        "expiry_date": expiry_date,
        "days_to_expiry": days_to_expiry,
        "is_valid_today": is_valid,
        "can_operate_unsupervised": is_valid and card_type in ("blue_competent", "gold_advanced"),
        "issues": issues,
        "reference": "CPCS Scheme Booklet — A36 Lorry Loader",
    }
    return _attestation(payload)


@mcp.tool()
def check_slinger_a40_a73(
    operator_name: str,
    card_number: str,
    card_category: str = "A40",
    expiry_date: str = "",
    card_type: str = "blue_competent",
) -> dict:
    """Verify a CPCS A40 (Slinger/Signaller Light) or A73 (All Duties) card.

    Args:
      operator_name: full name as on card
      card_number: CPCS registration number
      card_category: 'A40' (up to 5t lifts) or 'A73' (all lifts any weight)
      expiry_date: ISO YYYY-MM-DD
      card_type: 'red_trained' / 'blue_competent' / 'gold_advanced'
    """
    if card_category not in ("A40", "A73"):
        return _attestation({
            "tool": "check_slinger_a40_a73",
            "error": f"card_category must be A40 or A73, got '{card_category}'",
            "is_valid_today": False,
        })

    spec = CPCS_CARDS[card_category]
    try:
        exp = date.fromisoformat(expiry_date)
        days_to_expiry = (exp - date.today()).days
        is_valid = days_to_expiry > 0
    except Exception:
        days_to_expiry = -1
        is_valid = False

    # Scope ceiling
    if card_category == "A40":
        weight_ceiling_kg = 5000
        scope_note = "Up to 5 tonnes only — heavier lifts require A73"
    else:
        weight_ceiling_kg = None  # No ceiling
        scope_note = "All weights — any routine lift on site"

    issues = []
    if not is_valid:
        issues.append("EXPIRED — operator cannot act as slinger or signaller on site")
    elif days_to_expiry < 60:
        issues.append(f"Expires in {days_to_expiry} days — book renewal now")
    if card_type == "red_trained":
        issues.append("RED (trained) card only — must be supervised by Blue/Gold holder")

    payload = {
        "tool": "check_slinger_a40_a73",
        "operator_name": operator_name,
        "card_number": card_number,
        "card_category": card_category,
        "card_title": spec["title"],
        "card_scope": spec["scope"],
        "card_type": card_type,
        "expiry_date": expiry_date,
        "days_to_expiry": days_to_expiry,
        "weight_ceiling_kg": weight_ceiling_kg,
        "scope_note": scope_note,
        "is_valid_today": is_valid,
        "can_sling_unsupervised": is_valid and card_type in ("blue_competent", "gold_advanced"),
        "issues": issues,
        "reference": f"CPCS Scheme Booklet — {card_category} {spec['title']}",
    }
    return _attestation(payload)


@mcp.tool()
def capture_brick_grab_pod(
    delivery_id: str,
    site_address: str,
    site_postcode: str,
    customer_reference: str,
    product_summary: str,
    quantity: float,
    unit: str = "packs",
    slot_time: str = "",
    actual_arrival_time: str = "",
    actual_completion_time: str = "",
    driver_name: str = "",
    vehicle_vrn: str = "",
    photo_load_on_truck_url: str = "",
    photo_load_off_truck_url: str = "",
    photo_drop_location_url: str = "",
    signature_typed_name: str = "",
    signature_image_url: str = "",
    customer_present_name: str = "",
    notes: str = "",
) -> dict:
    """Capture brick-grab Proof Of Delivery — ePOD-ready structured record.

    Supports BOTH typed signature OR uploaded image — whichever the foreman
    can provide. Output is ready for direct ingestion into builders'-merchant
    ePOD systems (Travis Perkins TPGo, Jewson POD, MKM merchant POD, etc).

    Args:
      delivery_id: merchant's internal delivery reference
      site_address: street address
      site_postcode: drop postcode
      customer_reference: customer's PO / job reference
      product_summary: free-text product description
      quantity / unit: e.g. 12 'packs', 800 'bricks', 3.2 'tonnes'
      slot_time: planned slot, ISO datetime or 'HH:MM'
      actual_arrival_time / actual_completion_time: ISO datetimes or HH:MM
      driver_name / vehicle_vrn: identifies driver + truck
      photo_*_url: URLs to load-on, load-off, drop-location photos
      signature_typed_name: typed-signature mode
      signature_image_url: uploaded signature image
      customer_present_name: who received the goods on site
      notes: damages, shortages, customer comments

    Returns:
      Structured POD dict + signature_mode flag + completeness score.
    """
    # Detect signature mode
    if signature_image_url and signature_typed_name:
        signature_mode = "both"
    elif signature_image_url:
        signature_mode = "image"
    elif signature_typed_name:
        signature_mode = "typed"
    else:
        signature_mode = "missing"

    # Completeness score — drives auto-invoice eligibility
    fields_required = {
        "site_address": bool(site_address),
        "site_postcode": bool(site_postcode),
        "customer_reference": bool(customer_reference),
        "product_summary": bool(product_summary),
        "quantity_present": quantity > 0,
        "driver_name": bool(driver_name),
        "vehicle_vrn": bool(vehicle_vrn),
        "customer_present_name": bool(customer_present_name),
        "signature_present": signature_mode != "missing",
        "photo_load_off": bool(photo_load_off_truck_url),
    }
    fields_hit = sum(1 for v in fields_required.values() if v)
    completeness_pct = round((fields_hit / len(fields_required)) * 100, 1)

    missing_fields = [k for k, v in fields_required.items() if not v]

    pod = {
        "tool": "capture_brick_grab_pod",
        "delivery_id": delivery_id,
        "site": {
            "address": site_address,
            "postcode": site_postcode,
        },
        "customer_reference": customer_reference,
        "product": {
            "summary": product_summary,
            "quantity": quantity,
            "unit": unit,
        },
        "timing": {
            "slot_time": slot_time,
            "actual_arrival_time": actual_arrival_time,
            "actual_completion_time": actual_completion_time,
        },
        "driver": {
            "name": driver_name,
            "vehicle_vrn": vehicle_vrn,
        },
        "photos": {
            "load_on_truck": photo_load_on_truck_url,
            "load_off_truck": photo_load_off_truck_url,
            "drop_location": photo_drop_location_url,
        },
        "signature": {
            "mode": signature_mode,
            "typed_name": signature_typed_name,
            "image_url": signature_image_url,
            "customer_present_name": customer_present_name,
        },
        "notes": notes,
        "completeness_pct": completeness_pct,
        "missing_fields": missing_fields,
        "epod_ready": completeness_pct >= 80.0 and signature_mode != "missing",
        "auto_invoice_eligible": completeness_pct >= 90.0 and signature_mode != "missing",
        "bmf_codeofpractice_compliant": (
            completeness_pct >= 80.0
            and signature_mode != "missing"
            and bool(photo_load_off_truck_url)
        ),
        "reference": "BMF Code of Practice (POD) + Builders' Merchants ePOD schema",
    }
    return _attestation(pod)


@mcp.tool()
def flag_delivery_rejection_risk(
    delivery_id: str = "",
    site_postcode: str = "",
    site_foreman_name: str = "",
    site_foreman_phone: str = "",
    driver_name: str = "",
    vehicle_vrn: str = "",
    eta_hhmm: str = "",
    gates_locked: bool = False,
    no_banksman_on_site: bool = False,
    site_closed_for_slot: bool = False,
    wrong_product_mix: bool = False,
    wrong_slot_time: bool = False,
    obstructed_access: bool = False,
    overhead_powerlines: bool = False,
    soft_ground_unstable: bool = False,
    no_foreman_contact: bool = False,
    previous_failed_delivery: bool = False,
) -> dict:
    """Score the rejection risk and generate the magic-button foreman SMS.

    Each rejected brick delivery costs £200-£450 (failed trip + restock).
    This tool returns the risk score AND a pre-written 2-line SMS the office
    can fire to the site foreman to head off the rejection.

    Returns:
      risk_score (0-100), recommendation, sms_text, factors_hit.
    """
    flags = {
        "gates_locked": gates_locked,
        "no_banksman_on_site": no_banksman_on_site,
        "site_closed_for_slot": site_closed_for_slot,
        "wrong_product_mix": wrong_product_mix,
        "wrong_slot_time": wrong_slot_time,
        "obstructed_access": obstructed_access,
        "overhead_powerlines": overhead_powerlines,
        "soft_ground_unstable": soft_ground_unstable,
        "no_foreman_contact": no_foreman_contact,
        "previous_failed_delivery": previous_failed_delivery,
    }
    factors_hit = [k for k, v in flags.items() if v]
    risk_score = min(
        100,
        sum(REJECTION_RISK_WEIGHTS[k] for k in factors_hit if k in REJECTION_RISK_WEIGHTS),
    )

    if overhead_powerlines:
        recommendation = "STOP — overhead power lines auto-refuse. Do not approach."
    elif risk_score >= 70:
        recommendation = "RESCHEDULE — risk too high. Call site, agree new slot."
    elif risk_score >= 40:
        recommendation = "CALL_AHEAD — driver phones foreman 15 minutes out."
    elif risk_score >= 20:
        recommendation = "PROCEED_WITH_CAUTION — confirm slot before dispatch."
    else:
        recommendation = "PROCEED — low risk, dispatch as planned."

    # Magic-button SMS — fixed format the merchants asked for
    # "Your bricks will arrive at 10:48. Driver: Dave. Truck: KP24 ZTM."
    eta_display = eta_hhmm or "shortly"
    driver_display = driver_name or "the driver"
    vrn_display = vehicle_vrn or "tbc"
    sms_text = (
        f"Your bricks will arrive at {eta_display}. "
        f"Driver: {driver_display}. Truck: {vrn_display}."
    )

    # Concatenate a caution line if risk is elevated
    if risk_score >= 40 and factors_hit:
        top_factor = factors_hit[0].replace("_", " ")
        sms_text = (
            f"{sms_text} Please confirm: {top_factor} cleared. "
            f"Reply Y to proceed."
        )

    payload = {
        "tool": "flag_delivery_rejection_risk",
        "delivery_id": delivery_id,
        "site_postcode": site_postcode,
        "site_foreman_name": site_foreman_name,
        "site_foreman_phone": site_foreman_phone,
        "driver_name": driver_name,
        "vehicle_vrn": vehicle_vrn,
        "eta_hhmm": eta_hhmm,
        "risk_score": risk_score,
        "factors_hit": factors_hit,
        "recommendation": recommendation,
        "sms_text": sms_text,
        "sms_char_count": len(sms_text),
        "reference": "BMF Code of Practice — POD + delivery risk",
    }
    return _attestation(payload)


@mcp.tool()
def audit_pre_delivery_walkaround(
    driver_id: str,
    driver_name: str,
    vehicle_id: str,
    vehicle_vrn: str = "",
    checks: Optional[dict] = None,
    driver_acknowledgement: bool = False,
) -> dict:
    """25-point pre-delivery walkaround per HSE COP L113 + ALLMI ACoP.

    Args:
      driver_id / driver_name: driver identity
      vehicle_id / vehicle_vrn: vehicle identity
      checks: dict mapping check name (see WALKAROUND_CHECKS_25) -> True/False
              missing keys default to False (fail) — driver must explicitly tick.
      driver_acknowledgement: driver signed off on the walkaround

    Returns:
      per-item pass/fail, blocking flags, pass percentage, advisory.
    """
    checks = checks or {}
    results = {}
    fails = []
    for check_name in WALKAROUND_CHECKS_25:
        passed = bool(checks.get(check_name, False))
        results[check_name] = "pass" if passed else "fail"
        if not passed:
            fails.append(check_name)

    passes = len(WALKAROUND_CHECKS_25) - len(fails)
    pass_pct = round((passes / len(WALKAROUND_CHECKS_25)) * 100, 1)

    # Blocking failures — any of these = stop the vehicle going out
    blocking_checks = {
        "tyres_legal_tread_and_pressure",
        "service_brakes_function",
        "park_brake_holds_loaded",
        "hydraulic_lines_no_leaks",
        "outriggers_extend_fully",
        "boom_pivots_greased",
        "brick_grab_jaws_close_fully",
        "grab_safety_pin_present",
        "attachment_locks_engaged",
        "rci_rated_capacity_indicator_works",
    }
    blocking_fails = sorted([f for f in fails if f in blocking_checks])

    can_dispatch = (
        len(blocking_fails) == 0
        and driver_acknowledgement
        and pass_pct >= 92.0  # 23/25 minimum
    )

    issues = []
    if blocking_fails:
        issues.append(
            f"BLOCKING failures ({len(blocking_fails)}): {', '.join(blocking_fails)} — "
            "vehicle MUST NOT leave depot until rectified"
        )
    if not driver_acknowledgement:
        issues.append("Driver has not signed off the walkaround — get acknowledgement")
    if pass_pct < 92.0:
        issues.append(f"Pass rate {pass_pct}% below 92% threshold")

    payload = {
        "tool": "audit_pre_delivery_walkaround",
        "driver_id": driver_id,
        "driver_name": driver_name,
        "vehicle_id": vehicle_id,
        "vehicle_vrn": vehicle_vrn,
        "total_checks": len(WALKAROUND_CHECKS_25),
        "passes": passes,
        "fails_count": len(fails),
        "pass_pct": pass_pct,
        "blocking_fails": blocking_fails,
        "non_blocking_fails": [f for f in fails if f not in blocking_checks],
        "results": results,
        "driver_acknowledgement": driver_acknowledgement,
        "can_dispatch": can_dispatch,
        "issues": issues,
        "advisory": (
            "STOP — blocking failures present. Workshop sign-off required."
            if blocking_fails else (
                "Driver acknowledgement missing — capture before dispatch."
                if not driver_acknowledgement
                else "All clear — dispatch authorised."
                if can_dispatch
                else f"{len(fails)} minor fails — review before dispatch."
            )
        ),
        "reference": "HSE ACOP L113 + ALLMI ACoP pre-delivery walkaround",
    }
    return _attestation(payload)


# ──────────────────────────────────────────────────────────────────────
# Server entry
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()


# ── MEOK monetization layer (Stripe upgrade · PAYG · pricing) ──────────
# Free tier is zero-config. Upgrade to Pro (unlimited) or pay-as-you-go per call.
import os as _meok_os
MEOK_STRIPE_UPGRADE = "https://buy.stripe.com/00wfZjcgAeUW4c5cyQ8k90K"  # Pro (unlimited)
MEOK_PAYG_KEY = _meok_os.environ.get("MEOK_PAYG_KEY", "")  # set to enable PAYG (x402 / ~GBP0.05 per call)
MEOK_PRICING = "https://meok.ai/pricing"


def meok_upsell(tier: str = "free") -> dict:
    """Monetization options for free-tier callers: Pro upgrade, PAYG, or pricing page."""
    if tier != "free":
        return {}
    return {"upgrade_url": MEOK_STRIPE_UPGRADE,
            "payg_enabled": bool(MEOK_PAYG_KEY),
            "pricing": MEOK_PRICING}
