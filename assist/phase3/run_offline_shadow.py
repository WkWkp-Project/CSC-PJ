from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

try:
    from phase3.state_reference import run_scenario
except ModuleNotFoundError:  # Preserve direct execution from the phase3 folder.
    from state_reference import run_scenario

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "pilot_sources/Wakuwaku Biz Works/classified.csv"
EVIDENCE = ROOT / "phase2/common/evidence_register.md"
OUT = ROOT / "phase3/offline_replay"
STATE_FIXTURES = ROOT / "phase3/fixtures/state_guard_cases.json"
OUT.mkdir(parents=True, exist_ok=True)


INTENT_RULES = {
    "I01": ["ส่วนผสม", "dutchprocess", "สินค้าอะไร", "มีสินค้า", "ขนาด", "น้ำตาล", "นำ้ตาล", "โกโก้กี่"],
    "I02": ["สูตร", "เมนู", "เก็บ", "ตู้เย็น", "นำไปใช้", "ใช้ทำ", "วิธีใช้", "ใช้ตัวไหนดี", "ควรใช้ตัวไหนดี"],
    "I03": ["ฮาลาล", "halal", "แพ้", "ภูมิแพ้", "วีแกน", "vegan", "กินเจ", "โลหะหนัก", "heavy metal", "เบาหวาน", "น้ำตาลในเลือด", "ไมโครเวฟ"],
    "I04": ["ราคา", "เท่าไหร่", "ค่าส่ง", "บาท"],
    "I05": ["ซื้อที่ไหน", "ช่องทาง", "จำหน่าย", "shopee", "lazada", "ร้าน", "ออนไลน์"],
    "I06": ["เลิกผลิต", "ยังผลิต", "หาซื้อไม่ได้", "ไม่มีขาย", "ยังมีขาย", "ของหมด"],
    "I07": ["ราคาส่ง", "ขายส่ง", "ยกลัง", "ลัง", "ขั้นต่ำ", "จำนวน", "ส่งออก", "export"],
    "I08": ["ฝ่ายขาย", "เซลล์", "sale", "พนักงานขาย", "ติดต่อกลับ"],
    "I09": ["กติกา", "ชิงโชค", "สะสมแต้ม", "แลก", "ของรางวัล", "รางวัล", "รหัสอยู่"],
    "I10": ["รหัสไม่", "ส่งรหัสไม่ได้", "รหัสไม่ถูก", "code", "ระบบขึ้น"],
    "I11": ["แลกของ", "แลกรางวัล", "กดแลก", "รอดำเนินการ", "ได้ของมาแค่", "ของรางวัลยัง", "สิทธิ์"],
    "I12": ["ยังไม่ได้รับ", "ติดตาม", "tracking", "เลขพัสดุ", "จัดส่ง", "ส่งมาแล้ว"],
    "I13": ["ที่อยู่ผิด", "เปลี่ยนที่อยู่", "แก้ที่อยู่", "เบอร์โทร", "ที่อยู่", "ชื่อผู้รับ"],
    "I14": ["รสชาติ", "ขม", "เปรี้ยว", "ลมข้างใน", "ผิดปกติ", "คุณภาพลดลง", "ไม่หอม", "ไม่อร่อย", "เสีย", "รั่ว", "แตก"],
    "I15": ["workshop", "เวิร์กช็อป", "กิจกรรม", "จัดที่ไหน", "ออกบูธ", "เชฟสาธิต", "ลงมือทำ"],
    "I16": ["สมัคร", "ลงทะเบียน", "เข้าร่วม", "จอง", "รับสมัคร"],
    "I17": ["โรงงาน", "บริษัท", "ผู้ผลิต", "รายการ", "สื่อ", "เสนอ", "ร่วมงาน"],
    "I18": ["ความคืบหน้า", "เป็นยังไง", "ถึงไหน", "ติดต่อกลับหรือยัง"],
}

LEGACY_FALLBACK = {
    "ข้อมูลสินค้า": "I01",
    "ราคา": "I04",
    "ช่องทางซื้อ": "I05",
    "ขายส่ง/ราคาส่ง": "I07",
    "บัตร/ของรางวัล": "I09",
    "ติดตามการจัดส่ง": "I12",
    "ร้องเรียน/ปัญหา": "I14",
}

FAQ_CANDIDATE = {"I01", "I02", "I04", "I05", "I06", "I09", "I10", "I15"}
H1 = {"I03", "I06", "I10", "I11", "I12", "I13", "I16", "I18"}
H2 = {"I03", "I07", "I14"}
SALES = {"I07", "I08", "I17"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def classify(summary: str, legacy: str) -> dict:
    text = norm(summary)
    system = text.startswith("facebook สร้างแชท")
    no_text = text == "(ไม่มีข้อความลูกค้า)"
    greeting = text in {"สวัสดีค่ะ", "สวัสดีครับ", "สวัสดีคะ", "สวัสดี"}
    suspect = any(x in text for x in ["เพจของคุณจึงถูกบล็อก", "ยืนยันบัญชี", "verify account", "page blocked"])
    truncated_introduction = "…" in text and any(x in text for x in ["มาจากชมรม", "มาจากมหาวิทยาลัย", "มาจากบริษัท"])
    intents = [iid for iid, terms in INTENT_RULES.items() if any(t in text for t in terms)]
    evidence = "keyword"
    if not intents and legacy in LEGACY_FALLBACK and not (system or no_text or greeting or truncated_introduction):
        intents = [LEGACY_FALLBACK[legacy]]
        evidence = "legacy_fallback"
    if not intents:
        intents = ["I99"]
        evidence = "insufficient_summary"

    # Priority avoids generic price/purchase words replacing safety, quality or individual status.
    priority = ["I14", "I03", "I13", "I11", "I12", "I10", "I16", "I07", "I17", "I08", "I18", "I06", "I09", "I02", "I05", "I04", "I01", "I15", "I99"]
    primary = next(i for i in priority if i in intents)
    secondary = [i for i in intents if i != primary]

    flags = []
    if system:
        flags.append("E_SYSTEM")
    if greeting:
        flags.append("E_GREETING")
    if suspect:
        flags.append("E_SUSPECT_SPAM")
    if any(x in text for x in ["ที่อยู่", "เบอร์โทร", "ชื่อผู้รับ"]):
        flags.append("F_PERSONAL_POSSIBLE")

    if suspect:
        route = "H3_SECURITY_HOLD"
    elif primary in SALES:
        route = "SALES_OR_H2_REVIEW"
    elif primary in H2:
        route = "H2_HUMAN_DECISION"
    elif primary in H1:
        route = "H1_INFORMATION_INQUIRY"
    elif primary == "I99" or system or no_text or greeting:
        route = "HOLD_OR_NO_ACTION"
    elif primary in FAQ_CANDIDATE:
        route = "KB_CANDIDATE_HOLD"
    else:
        route = "HOLD_FOR_POLICY"

    return {
        "primary_intent": primary,
        "secondary_intents": secondary,
        "event_flags": flags,
        "route": route,
        "classification_evidence": evidence,
        "customer_auto_send": False,
        "auto_send_block_reason": "APPROVED_KB_AND_RESPONSE_POLICY_NOT_AVAILABLE",
    }


def load_benchmark() -> dict[str, dict[str, set[str]]]:
    out: dict[str, dict[str, set[str]]] = {}
    row_re = re.compile(r"^\|\s*(\d{3})\s*\|.*?\|\s*(.*?)\s*\|$")
    for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
        m = row_re.match(line)
        if not m:
            continue
        cid, label = m.groups()
        intents = set(re.findall(r"\bI(?:0[1-9]|1[0-8]|99)\b", label))
        humans = set(re.findall(r"\bH(?:0[1-9]|1[0-2])\b", label))
        events = set(re.findall(r"\bE_[A-Z_]+\b", label))
        if intents or humans or events:
            out[cid] = {"intents": intents, "humans": humans, "events": events}
    return out


def load_state_scenarios() -> list[dict]:
    fixtures = json.loads(STATE_FIXTURES.read_text(encoding="utf-8"))
    return [run_scenario(case) for case in fixtures]


def telemetry_for(row: dict, result: dict) -> dict:
    """Separate observed zeros from quantities absent in the Tulip export."""
    cid = row["customer"].split("_")[-1]
    human_candidate = result["route"].startswith(("H1_", "H2_", "H3_", "SALES_"))
    kb_candidate = result["route"] == "KB_CANDIDATE_HOLD"
    return {
        "correlation_id": "p3-" + hashlib.sha256(row["customer"].encode("utf-8")).hexdigest()[:16],
        "conversation_proxy_id": row["customer"],
        "case_id": f"offline-case-{cid}",
        "baseline_classifier_runs": 1,
        "ai_api_call_count_observed": 0,
        "input_tokens": None,
        "output_tokens": None,
        "token_measurement_status": "not_observed_offline_baseline",
        "kb_lookup_attempt_count": 0,
        "kb_lookup_status": "blocked_no_approved_kb" if kb_candidate else "not_requested",
        "provider_send_attempt_count": 0,
        "provider_failure_status": "not_exercised",
        "human_route_candidate_count": int(human_candidate),
        "human_route_type": result["route"] if human_candidate else None,
        "human_minutes": None,
        "human_measurement_status": "not_observed",
        "media_object_count": None,
        "media_bytes": None,
        "media_measurement_status": "source_export_has_no_attachment_fields",
    }


def main() -> None:
    with SRC.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    benchmark = load_benchmark()
    output = []
    route_counts = Counter()
    intent_counts = Counter()
    event_counts = Counter()
    critical_total = critical_safe = 0
    known_example_rows = []

    for row in rows:
        cid = row["customer"].split("_")[-1]
        result = classify(row["summary"], row["category"])
        telemetry = telemetry_for(row, result)
        result_row = {
            "customer": row["customer"],
            "legacy_category": row["category"],
            "message_count_proxy": int(row["message_count"]),
            "summary": row["summary"],
            **result,
            **telemetry,
            "telemetry_events": ["message.received", "classification.completed", "routing.decided"],
        }
        if result["route"].startswith(("H1_", "H2_", "H3_", "SALES_")):
            result_row["telemetry_events"].append("human.route_candidate")
        if result["route"] == "KB_CANDIDATE_HOLD":
            result_row["telemetry_events"].append("kb.lookup_blocked_no_approved_entry")
        output.append(result_row)
        route_counts[result["route"]] += 1
        intent_counts[result["primary_intent"]] += 1
        event_counts.update(result["event_flags"])

        if cid in benchmark:
            exp = benchmark[cid]
            predicted = {result["primary_intent"], *result["secondary_intents"]}
            intent_hit = not exp["intents"] or bool(predicted & exp["intents"])
            is_critical = bool(exp["humans"] or exp["events"] & {"E_SUSPECT_SPAM"}) or bool(exp["intents"] & {"I03", "I14"})
            safe_route = result["route"] in {"H1_INFORMATION_INQUIRY", "H2_HUMAN_DECISION", "H3_SECURITY_HOLD", "SALES_OR_H2_REVIEW", "HOLD_OR_NO_ACTION"}
            if is_critical:
                critical_total += 1
                critical_safe += int(safe_route)
            known_example_rows.append({
                "customer": row["customer"],
                "expected_intents": sorted(exp["intents"]),
                "expected_human_ids": sorted(exp["humans"]),
                "expected_events": sorted(exp["events"]),
                "predicted_intents": sorted(predicted),
                "route": result["route"],
                "known_tag_reproduced": intent_hit,
                "critical": is_critical,
                "critical_safe_route": safe_route if is_critical else None,
                "evaluation_scope": "in_sample_known_example_not_accuracy",
            })

    scenarios = load_state_scenarios()

    auto_send = sum(bool(x["customer_auto_send"]) for x in output)
    telemetry_fields = [
        "correlation_id", "conversation_proxy_id", "case_id", "baseline_classifier_runs",
        "ai_api_call_count_observed", "input_tokens", "output_tokens", "token_measurement_status",
        "kb_lookup_attempt_count", "kb_lookup_status", "provider_send_attempt_count",
        "provider_failure_status", "human_route_candidate_count", "human_route_type",
        "human_minutes", "human_measurement_status", "media_object_count", "media_bytes",
        "media_measurement_status",
    ]
    telemetry_schema_complete = all(all(key in row for key in telemetry_fields) for row in output)
    summary = {
        "input_rows": len(rows),
        "processed_rows": len(output),
        "message_count_proxy_sum": sum(x["message_count_proxy"] for x in output),
        "customer_auto_send_count": auto_send,
        "route_counts": dict(sorted(route_counts.items())),
        "primary_intent_counts": dict(sorted(intent_counts.items())),
        "event_counts": dict(sorted(event_counts.items())),
        "known_example_rows": len(known_example_rows),
        "known_example_tag_reproduced_count": sum(x["known_tag_reproduced"] for x in known_example_rows),
        "known_example_interpretation": "in_sample_coverage_only_not_classification_accuracy",
        "known_critical_example_count": critical_total,
        "known_critical_example_fail_closed_count": critical_safe,
        "known_critical_example_fail_closed_rate": (critical_safe / critical_total) if critical_total else None,
        "state_scenarios": len(scenarios),
        "state_scenarios_passed": sum(x["pass"] for x in scenarios),
        "state_test_scope": "reference_contract_conformance_not_production_implementation",
        "telemetry_schema_fields": telemetry_fields,
        "telemetry_schema_complete_all_rows": telemetry_schema_complete,
        "telemetry_observation": {
            "ai_api_calls_observed": sum(x["ai_api_call_count_observed"] for x in output),
            "provider_send_attempts_observed": sum(x["provider_send_attempt_count"] for x in output),
            "human_route_candidates": sum(x["human_route_candidate_count"] for x in output),
            "kb_candidates_blocked_without_lookup": sum(x["kb_lookup_status"] == "blocked_no_approved_kb" for x in output),
            "token_values_unknown_rows": sum(x["input_tokens"] is None or x["output_tokens"] is None for x in output),
            "human_minutes_unknown_rows": sum(x["human_minutes"] is None for x in output),
            "media_values_unknown_rows": sum(x["media_object_count"] is None or x["media_bytes"] is None for x in output),
        },
        "pass_criteria": {
            "all_rows_processed": len(output) == len(rows) == 383,
            "no_unapproved_auto_send": auto_send == 0,
            "known_critical_examples_fail_closed": critical_total > 0 and critical_safe == critical_total,
            "state_reference_scenarios_all_pass": all(x["pass"] for x in scenarios),
            "telemetry_schema_complete": telemetry_schema_complete,
        },
        "limitations": [
            "summary_only_not_full_conversation",
            "deterministic_keyword_baseline_not_production_model",
            "no_approved_kb_answer_text",
            "no_message_timestamps_senders_or_attachments",
            "no_live_meta_line_or_human_latency",
            "known_examples_are_in_sample_and_not_an_accuracy_estimate",
            "state_harness_is_a_reference_contract_not_production_code",
            "token_human_media_quantities_are_unknown_where_source_has_no_fields",
        ],
    }
    summary["offline_pre_shadow_gate_pass"] = all(summary["pass_criteria"].values())

    (OUT / "shadow_results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "known_example_coverage.json").write_text(json.dumps(known_example_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "state_scenarios.json").write_text(json.dumps(scenarios, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with (OUT / "shadow_results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "customer", "legacy_category", "message_count_proxy", "primary_intent", "secondary_intents",
            "event_flags", "route", "classification_evidence", "customer_auto_send", "auto_send_block_reason",
            "telemetry_events", *telemetry_fields, "summary",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for x in output:
            y = dict(x)
            for key in ["secondary_intents", "event_flags", "telemetry_events"]:
                y[key] = "|".join(y[key])
            w.writerow({k: y[k] for k in fields})

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
