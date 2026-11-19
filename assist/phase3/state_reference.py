from __future__ import annotations

from copy import deepcopy


def initial_snapshot(state: str, initial: dict | None = None) -> dict:
    snapshot = {
        "state": state,
        "provider_calls": 0,
        "business_replies": 0,
        "safety_reserve": None,
        "human_sessions": 0,
        "derivative_writes": 0,
        "external_instruction_effects": 0,
    }
    snapshot.update(initial or {})
    return snapshot


def apply_step(snapshot: dict, event: str, guards: dict | None = None) -> dict:
    """Executable reference contract only; this is not production implementation."""
    s = deepcopy(snapshot)
    g = guards or {}
    state = s["state"]

    fixed = {
        ("NONE", "VALID_INBOUND"): "PROVISIONAL",
        ("PROVISIONAL", "START_AGGREGATION"): "AGGREGATING",
        ("AGGREGATING", "BUNDLE_CLOSE_CURRENT"): "PROCESSING",
        ("NEEDS_CUSTOMER", "CUSTOMER_REPLY"): "AGGREGATING",
        ("CUSTOMER_WAIT_EXPIRED", "CUSTOMER_REPLY"): "AGGREGATING",
        ("PROCESSING", "ASK_WAKU"): "WAITING_WAKU",
        ("WAITING_WAKU", "ASK_BRAND"): "WAITING_BRAND",
        ("HUMAN_WAIT_OVERDUE", "MATCHED_FINAL_RESPONSE"): "PROCESSING",
        ("SENDING", "CORRECTION_OR_CANCEL"): "RECOVERY_HOLD",
        ("PROCESSING", "HARD_CAP"): "CAP_RECEIPT_PENDING",
        ("CAP_RECEIPT_PENDING", "RECEIPT_FINAL_OR_NOT_REQUIRED"): "NEXT_CYCLE_QUEUE",
        ("RAW_PII", "DELETE_COMMIT"): "TOMBSTONED",
        ("LINE_LINK", "MEMBERSHIP_REVOKED"): "ACCESS_DENIED",
        ("UNTRUSTED_INPUT", "INJECTION_DETECTED"): "QUARANTINED",
    }
    if (state, event) in fixed:
        s["state"] = fixed[(state, event)]
        return s

    if event == "CONCURRENT_APPROVE_SEND_CANCEL":
        if g.get("cancel_committed_before_provider_cas"):
            s["state"] = "CANCELLED"
            s["provider_calls"] = 0
            s["business_replies"] = 0
        else:
            s["state"] = "RECOVERY_HOLD"
        return s

    if state == "PROCESSING" and event == "CLARIFICATION_SENT":
        s["state"] = "NEEDS_CUSTOMER" if g.get("current_bundle") and g.get("sent") else "BLOCKED"
        return s

    if state in {"WAITING_WAKU", "WAITING_BRAND"} and event == "MATCHED_FINAL_RESPONSE":
        s["state"] = "PROCESSING" if g.get("case_match") and g.get("final") and not g.get("conflicting") else state
        return s

    if state in {"WAITING_WAKU", "WAITING_BRAND"} and event == "AMBIGUOUS_OR_CONFLICTING_RESPONSE":
        return s

    if state == "PROCESSING" and event == "MANUAL_OWNER_ACQUIRED":
        s["state"] = "MANUAL"
        return s
    if state == "MANUAL" and event == "ANSWER_APPROVED":
        return s
    if state == "MANUAL" and event == "MANUAL_OWNER_RELEASED":
        s["state"] = "PROCESSING" if g.get("explicit_release") else "MANUAL"
        return s

    if state == "PROCESSING" and event == "ANSWER_APPROVED":
        required = ["current_answer", "current_bundle", "current_policy", "no_unprocessed_input", "no_manual_owner", "no_active_reply"]
        s["state"] = "READY_TO_SEND" if all(g.get(k) for k in required) else "BLOCKED"
        return s
    if event == "ANSWER_APPROVED":
        s["state"] = "BLOCKED"
        return s
    if state == "READY_TO_SEND" and event == "PROVIDER_SENT":
        s["state"] = "ANSWERED"
        s["provider_calls"] += 1
        s["business_replies"] += 1
        return s
    if state == "READY_TO_SEND" and event == "PROVIDER_TIMEOUT":
        s["state"] = "RECOVERY_HOLD"
        s["provider_calls"] += 1
        return s
    if state == "RECOVERY_HOLD" and event == "LATE_PROVIDER_SUCCESS":
        if g.get("idempotency_match") and g.get("no_retry_send"):
            s["state"] = "ANSWERED"
            s["business_replies"] = 1
        return s

    if state == "PROCESSING" and event == "ATOMIC_SAFETY_COMPETE":
        remaining = int(s.get("safety_reserve") or 0)
        contenders = int(g.get("contenders", 1))
        allocated = min(remaining, contenders, 1)
        s["safety_reserve"] = remaining - allocated
        s["human_sessions"] += allocated
        s["state"] = "WAITING_HUMAN" if allocated else "SAFETY_EXHAUSTED_HOLD"
        return s

    if state == "TOMBSTONED" and event in {"LATE_DERIVATIVE", "PROVIDER_CALLBACK", "BACKUP_RESTORE_WORKER"}:
        s["state"] = "LATE_DERIVATIVE_REJECTED"
        s["derivative_writes"] = 0
        return s

    if state == "UNTRUSTED_INPUT" and event == "MODEL_TREATS_AS_INSTRUCTION":
        s["state"] = "POLICY_BLOCKED"
        s["external_instruction_effects"] = 0
        return s

    s["state"] = "INVALID_TRANSITION"
    return s


def run_scenario(case: dict) -> dict:
    snapshot = initial_snapshot(case["start"], case.get("initial"))
    trace = [snapshot["state"]]
    for step in case["steps"]:
        snapshot = apply_step(snapshot, step["event"], step.get("guards"))
        trace.append(snapshot["state"])
    expected = case["expected"]
    passed = all(snapshot.get(key) == value for key, value in expected.items())
    return {
        "id": case["id"],
        "requirement": case["requirement"],
        "trace": trace,
        "expected": expected,
        "actual": snapshot,
        "pass": passed,
        "scope": "reference_contract_not_production_code",
    }
