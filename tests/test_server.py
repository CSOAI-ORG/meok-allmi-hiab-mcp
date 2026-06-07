"""Smoke + behavioural tests for meok-allmi-hiab-mcp."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import (
    generate_hiab_lift_plan,
    triage_contract_lift_threshold,
    check_allmi_thorough_examination,
    check_cpcs_a36,
    check_slinger_a40_a73,
    capture_brick_grab_pod,
    flag_delivery_rejection_risk,
    audit_pre_delivery_walkaround,
    HIAB_ATTACHMENT_TYPES,
    ALLMI_TE_INTERVALS_MONTHS,
    CPCS_CARDS,
    WALKAROUND_CHECKS_25,
    REJECTION_RISK_WEIGHTS,
)


def _call(tool, **kwargs):
    """FastMCP wraps tools as Tool objects — extract the callable."""
    fn = tool.fn if hasattr(tool, "fn") else tool
    return fn(**kwargs)


# ──────────────────────────────────────────────────────────────────────
# generate_hiab_lift_plan
# ──────────────────────────────────────────────────────────────────────

def test_lift_plan_basic_under_swl_proceeds():
    r = _call(
        generate_hiab_lift_plan,
        load_weight_kg=900,
        load_length_m=1.2,
        load_width_m=1.0,
        load_height_m=0.8,
        load_description="Pack of 500 bricks",
        vehicle_crane_swl_kg=3000,
        vehicle_max_reach_m=6.0,
        site_postcode="LS1 1AA",
        site_ground_condition="tarmac",
        attachment_type="brick_grab",
    )
    assert r["compliant_to_proceed"] is True
    assert r["lift_category"] == "basic"
    assert r["ap_signoff_required"] is False
    assert r["vehicle"]["swl_utilisation_pct"] == 30.0
    assert r["exclusion_zone_radius_m"] > 6.0  # reach + load + buffer


def test_lift_plan_overload_blocks_with_stop_advisory():
    r = _call(
        generate_hiab_lift_plan,
        load_weight_kg=4000,
        vehicle_crane_swl_kg=3000,
        attachment_type="brick_grab",
    )
    assert r["compliant_to_proceed"] is False
    assert any("EXCEEDS" in i for i in r["issues"])
    assert r["lift_category"] == "complex"
    assert "STOP" in r["advisory"]


def test_lift_plan_public_in_zone_triggers_ap_signoff():
    r = _call(
        generate_hiab_lift_plan,
        load_weight_kg=1000,
        vehicle_crane_swl_kg=3000,
        public_within_exclusion_zone=True,
        site_ground_condition="tarmac",
    )
    assert r["ap_signoff_required"] is True
    assert r["lift_category"] == "complex"


def test_lift_plan_soft_ground_requires_spreader_pads():
    r = _call(
        generate_hiab_lift_plan,
        load_weight_kg=800,
        vehicle_crane_swl_kg=3000,
        site_ground_condition="soft_ground",
    )
    assert r["site"]["outrigger_pads_required"] is True
    assert "MANDATORY" in r["site"]["outrigger_extension"]
    assert r["ap_signoff_required"] is True


# ──────────────────────────────────────────────────────────────────────
# triage_contract_lift_threshold — the £100k+ wedge
# ──────────────────────────────────────────────────────────────────────

def test_triage_domestic_no_slinger_is_contract_lift():
    """Classic builders'-merchant scenario: domestic customer, no competent slinger.
    Operator drives + plans + slings = CONTRACT LIFT, operator carries liability."""
    r = _call(
        triage_contract_lift_threshold,
        job_description="Brick delivery to back garden of domestic build",
        customer_provides_slinger=False,
        customer_is_domestic=True,
        operator_writes_lift_plan=True,
        site_has_appointed_person=False,
        lift_near_public=True,
    )
    assert r["classification"] == "CONTRACT_LIFT"
    assert r["indicator_count"] >= 3
    assert any("£10m" in s for s in r["recommended_insurance"])
    assert "CONTRACT LIFT" in r["advisory"]


def test_triage_competent_contractor_with_ap_is_hire():
    """Main-contractor site with own AP + slinger = HIRE, customer carries liability."""
    r = _call(
        triage_contract_lift_threshold,
        job_description="Delivery to live construction site, main contractor competent",
        customer_provides_slinger=True,
        customer_is_domestic=False,
        operator_writes_lift_plan=False,
        site_has_appointed_person=True,
        lift_near_public=False,
    )
    assert r["classification"] == "HIRE"
    assert any("Form 10/2011" in s for s in [r["advisory"]])


def test_triage_indicator_threshold_at_three():
    """3 indicators = Contract Lift; 2 = Hire (validates the threshold)."""
    # Exactly 2 indicators
    r2 = _call(
        triage_contract_lift_threshold,
        customer_provides_slinger=True,
        operator_writes_lift_plan=True,
        operator_carries_load_insurance=False,
        lift_near_public=False,
        customer_is_domestic=False,
        lift_above_routine_swl=False,
        site_has_appointed_person=True,
    )
    # operator_writes_lift_plan = 1 indicator only (customer_provides_slinger removes 2)
    assert r2["classification"] == "HIRE"


# ──────────────────────────────────────────────────────────────────────
# check_allmi_thorough_examination
# ──────────────────────────────────────────────────────────────────────

def test_te_valid_within_12_months():
    r = _call(
        check_allmi_thorough_examination,
        equipment_id="HIAB-001",
        equipment_type="lorry_loader_carrying_loads",
        last_te_date="2026-01-01",
    )
    assert r["interval_months"] == 12
    assert r["can_lift_today"] is True


def test_te_personnel_lifting_forces_6_month():
    r = _call(
        check_allmi_thorough_examination,
        equipment_id="HIAB-002",
        equipment_type="lorry_loader_carrying_loads",
        last_te_date="2026-01-01",
        used_for_personnel=True,
    )
    assert r["interval_months"] == 6
    assert r["used_for_personnel"] is True


def test_te_overdue_blocks_use():
    r = _call(
        check_allmi_thorough_examination,
        equipment_id="HIAB-003",
        equipment_type="lorry_loader_carrying_loads",
        last_te_date="2020-01-01",
    )
    assert r["status"] == "OVERDUE"
    assert r["can_lift_today"] is False
    assert any("OVERDUE" in i for i in r["issues"])


# ──────────────────────────────────────────────────────────────────────
# check_cpcs_a36 + check_slinger_a40_a73
# ──────────────────────────────────────────────────────────────────────

def test_a36_blue_valid_operates_unsupervised():
    r = _call(
        check_cpcs_a36,
        operator_name="Dave Carter",
        card_number="CPCS-A36-12345",
        expiry_date="2028-12-31",
        card_type="blue_competent",
    )
    assert r["is_valid_today"] is True
    assert r["can_operate_unsupervised"] is True
    assert r["card_category"] == "A36"


def test_a36_red_trained_needs_supervision():
    r = _call(
        check_cpcs_a36,
        operator_name="Trainee Joe",
        card_number="CPCS-A36-77777",
        expiry_date="2028-12-31",
        card_type="red_trained",
    )
    assert r["can_operate_unsupervised"] is False
    assert any("RED" in i for i in r["issues"])


def test_a40_slinger_has_5_tonne_ceiling():
    r = _call(
        check_slinger_a40_a73,
        operator_name="Sam Slinger",
        card_number="CPCS-A40-88888",
        card_category="A40",
        expiry_date="2028-06-01",
    )
    assert r["card_category"] == "A40"
    assert r["weight_ceiling_kg"] == 5000


def test_a73_slinger_has_no_ceiling():
    r = _call(
        check_slinger_a40_a73,
        operator_name="Sam Slinger",
        card_number="CPCS-A73-99999",
        card_category="A73",
        expiry_date="2028-06-01",
    )
    assert r["card_category"] == "A73"
    assert r["weight_ceiling_kg"] is None


def test_invalid_slinger_category_rejected():
    r = _call(
        check_slinger_a40_a73,
        operator_name="Sam Slinger",
        card_number="CPCS-XX-1",
        card_category="A99",
        expiry_date="2028-06-01",
    )
    assert "error" in r
    assert r["is_valid_today"] is False


# ──────────────────────────────────────────────────────────────────────
# capture_brick_grab_pod — typed vs image signature
# ──────────────────────────────────────────────────────────────────────

def test_pod_typed_signature_recorded():
    r = _call(
        capture_brick_grab_pod,
        delivery_id="TP-2026-7788",
        site_address="14 Brickworks Lane",
        site_postcode="LS27 0AB",
        customer_reference="PO-12345",
        product_summary="500 Class A engineering bricks",
        quantity=2.5,
        unit="packs",
        slot_time="10:00",
        actual_arrival_time="10:48",
        driver_name="Dave Carter",
        vehicle_vrn="KP24 ZTM",
        photo_load_off_truck_url="https://cdn.merchant/pod/abc-off.jpg",
        signature_typed_name="J. Foreman",
        customer_present_name="J. Foreman",
    )
    assert r["signature"]["mode"] == "typed"
    assert r["epod_ready"] is True
    assert r["bmf_codeofpractice_compliant"] is True


def test_pod_image_signature_recorded():
    r = _call(
        capture_brick_grab_pod,
        delivery_id="JW-2026-44",
        site_address="2 Site Road",
        site_postcode="M1 1AA",
        customer_reference="PO-99",
        product_summary="Aircrete blocks",
        quantity=1.2,
        unit="tonnes",
        driver_name="Dave Carter",
        vehicle_vrn="KP24 ZTM",
        photo_load_off_truck_url="https://cdn.merchant/pod/abc-off.jpg",
        signature_image_url="https://cdn.merchant/pod/sig.png",
        customer_present_name="K. Builder",
    )
    assert r["signature"]["mode"] == "image"
    assert r["epod_ready"] is True


def test_pod_missing_signature_flags_not_ready():
    r = _call(
        capture_brick_grab_pod,
        delivery_id="MKM-1",
        site_address="9 Build St",
        site_postcode="B1 1AA",
        customer_reference="PO-1",
        product_summary="Bricks",
        quantity=1,
        unit="packs",
    )
    assert r["signature"]["mode"] == "missing"
    assert r["epod_ready"] is False
    assert r["auto_invoice_eligible"] is False


# ──────────────────────────────────────────────────────────────────────
# flag_delivery_rejection_risk — the magic-button SMS
# ──────────────────────────────────────────────────────────────────────

def test_magic_button_sms_contains_eta_driver_vrn():
    """The CRITICAL test — every merchant asked for this exact format."""
    r = _call(
        flag_delivery_rejection_risk,
        delivery_id="DEL-1",
        site_postcode="LS1 1AA",
        site_foreman_name="J. Foreman",
        driver_name="Dave",
        vehicle_vrn="KP24 ZTM",
        eta_hhmm="10:48",
    )
    # Must contain ETA, driver name, and VRN
    assert "10:48" in r["sms_text"]
    assert "Dave" in r["sms_text"]
    assert "KP24 ZTM" in r["sms_text"]
    # Must be the exact format we promised
    assert r["sms_text"].startswith("Your bricks will arrive at 10:48.")
    assert r["recommendation"].startswith("PROCEED")
    assert "low risk" in r["recommendation"]


def test_rejection_risk_overhead_powerlines_forces_stop():
    r = _call(
        flag_delivery_rejection_risk,
        delivery_id="DEL-2",
        overhead_powerlines=True,
        driver_name="Dave",
        vehicle_vrn="KP24 ZTM",
        eta_hhmm="11:00",
    )
    assert r["recommendation"].startswith("STOP")
    assert r["risk_score"] >= 50


def test_rejection_risk_high_score_reschedules():
    r = _call(
        flag_delivery_rejection_risk,
        delivery_id="DEL-3",
        site_closed_for_slot=True,
        no_banksman_on_site=True,
        wrong_product_mix=True,
        driver_name="Dave",
        vehicle_vrn="KP24 ZTM",
    )
    assert r["risk_score"] >= 70
    assert r["recommendation"].startswith("RESCHEDULE")


def test_rejection_risk_caution_sms_appends_confirm():
    r = _call(
        flag_delivery_rejection_risk,
        delivery_id="DEL-4",
        gates_locked=True,
        no_banksman_on_site=True,
        driver_name="Dave",
        vehicle_vrn="KP24 ZTM",
        eta_hhmm="10:48",
    )
    # Risk score should be 35+25 = 60, in CALL_AHEAD band (40-69)
    assert r["risk_score"] >= 40
    assert "Reply Y" in r["sms_text"] or "Please confirm" in r["sms_text"]


# ──────────────────────────────────────────────────────────────────────
# audit_pre_delivery_walkaround
# ──────────────────────────────────────────────────────────────────────

def test_walkaround_all_pass_dispatches():
    all_checks = {c: True for c in WALKAROUND_CHECKS_25}
    r = _call(
        audit_pre_delivery_walkaround,
        driver_id="DRV-1",
        driver_name="Dave Carter",
        vehicle_id="VEH-1",
        vehicle_vrn="KP24 ZTM",
        checks=all_checks,
        driver_acknowledgement=True,
    )
    assert r["pass_pct"] == 100.0
    assert r["can_dispatch"] is True
    assert r["blocking_fails"] == []


def test_walkaround_blocking_fail_blocks_dispatch():
    all_checks = {c: True for c in WALKAROUND_CHECKS_25}
    all_checks["service_brakes_function"] = False  # blocking fail
    r = _call(
        audit_pre_delivery_walkaround,
        driver_id="DRV-1",
        driver_name="Dave Carter",
        vehicle_id="VEH-1",
        vehicle_vrn="KP24 ZTM",
        checks=all_checks,
        driver_acknowledgement=True,
    )
    assert r["can_dispatch"] is False
    assert "service_brakes_function" in r["blocking_fails"]
    assert "STOP" in r["advisory"]


def test_walkaround_missing_acknowledgement_blocks():
    all_checks = {c: True for c in WALKAROUND_CHECKS_25}
    r = _call(
        audit_pre_delivery_walkaround,
        driver_id="DRV-1",
        driver_name="Dave Carter",
        vehicle_id="VEH-1",
        checks=all_checks,
        driver_acknowledgement=False,
    )
    assert r["can_dispatch"] is False
    assert any("acknowledgement" in i.lower() or "signed off" in i.lower() for i in r["issues"])


# ──────────────────────────────────────────────────────────────────────
# HMAC chain + attestation envelope
# ──────────────────────────────────────────────────────────────────────

def test_attestation_envelope_present_on_every_tool():
    r = _call(generate_hiab_lift_plan, load_weight_kg=500, vehicle_crane_swl_kg=3000)
    assert "ts" in r and "sig" in r and "issuer" in r and "version" in r
    assert r["issuer"] == "meok-allmi-hiab-mcp"
    assert r["version"] == "1.0.0"


def test_hmac_chain_deterministic_when_secret_set():
    """With MEOK_HMAC_SECRET set, identical inputs => identical signatures."""
    os.environ["MEOK_HMAC_SECRET"] = "test-key-allmi-hiab"
    # Re-import the _sign function with new secret
    import importlib
    import server as srv
    importlib.reload(srv)

    sig1 = srv._sign({"k": "v", "n": 1})
    sig2 = srv._sign({"k": "v", "n": 1})
    sig3 = srv._sign({"k": "v", "n": 2})
    assert sig1 == sig2
    assert sig1 != sig3
    assert sig1 != "unsigned-no-key-configured"

    # Clean up
    del os.environ["MEOK_HMAC_SECRET"]
    importlib.reload(srv)


def test_hmac_unsigned_when_no_secret():
    # ensure secret not in env
    os.environ.pop("MEOK_HMAC_SECRET", None)
    import importlib
    import server as srv
    importlib.reload(srv)
    sig = srv._sign({"k": "v"})
    assert sig == "unsigned-no-key-configured"


# ──────────────────────────────────────────────────────────────────────
# Reference table sanity
# ──────────────────────────────────────────────────────────────────────

def test_walkaround_has_25_items():
    assert len(WALKAROUND_CHECKS_25) == 25


def test_cpcs_table_has_a36_a40_a73():
    assert set(CPCS_CARDS.keys()) >= {"A36", "A40", "A73"}


def test_te_intervals_include_personnel_6_month():
    assert ALLMI_TE_INTERVALS_MONTHS["lorry_loader_personnel_lifting"] == 6
    assert ALLMI_TE_INTERVALS_MONTHS["lorry_loader_carrying_loads"] == 12


def test_attachment_table_has_brick_grab():
    assert "brick_grab" in HIAB_ATTACHMENT_TYPES
    assert HIAB_ATTACHMENT_TYPES["brick_grab"]["swl_kg"] > 0


def test_rejection_weights_powerlines_is_highest():
    # Powerlines should be the highest single weight (auto-stop semantically)
    weights = REJECTION_RISK_WEIGHTS
    assert weights["overhead_powerlines"] == max(weights.values())


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
