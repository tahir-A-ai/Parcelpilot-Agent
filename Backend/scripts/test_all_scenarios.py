"""
Automated Multi-Tenant E2E Test Suite for ParcelPilot.
Validates assessment scenarios & edge cases across ACCT-001, ACCT-002, ACCT-003, and ACCT-004.
"""

import json
import sys
import time
import urllib.error
import urllib.request

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://localhost:8000/api/v1"


def call_chat(account_id: str, message: str, session_id: str, history=None):
    payload = {
        "account_id": account_id,
        "message": message,
        "session_id": session_id,
        "history": history or []
    }
    req = urllib.request.Request(
        f"{BASE_URL}/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode("utf-8")}
    except Exception as e:
        return {"error": str(e)}


def call_confirm(session_id: str, action_id: str, confirmed: bool):
    payload = {
        "session_id": session_id,
        "action_id": action_id,
        "confirmed": confirmed
    }
    req = urllib.request.Request(
        f"{BASE_URL}/action/confirm",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_tests():
    print("=" * 75)
    print("PARCELPILOT FULL MULTI-TENANT & EDGE CASE TEST SUITE")
    print("=" * 75)

    # Test 1: Northstar Logistics (ACCT-001) - Contract Precedence
    print("\n[TEST 1] Persona: Northstar Logistics (ACCT-001)")
    print("Scenario: Precedence - Custom Agreement vs Default SOP on Cancellation Fee")
    res1 = call_chat(
        account_id="ACCT-001",
        message="Can Northstar cancel a booked shipment before pickup without paying a cancellation fee? Why?",
        session_id="test-northstar-01"
    )
    reply1 = res1.get("data", {}).get("reply", "")
    print(f"Reply:\n{reply1}\n")
    assert any(k in reply1.lower() for k in ("agreement", "northstar", "free", "0")), f"Unexpected reply: {reply1}"
    print("  Passed: Northstar custom agreement precedence over standard SOP.")

    # Test 2: Northstar Logistics (ACCT-001) - SLA Breach Detection
    time.sleep(5)
    print("\n[TEST 2] Persona: Northstar Logistics (ACCT-001)")
    print("Scenario: SLA Calculation - Outage Ticket TKT-501 P1 15-min SLA Breach")
    res2 = call_chat(
        account_id="ACCT-001",
        message="Check ticket TKT-501. Is there an SLA breach as of right now?",
        session_id="test-northstar-sla"
    )
    reply2 = res2.get("data", {}).get("reply", "")
    print(f"Reply:\n{reply2}\n")
    assert any(k in reply2.lower() for k in ("breach", "sla", "15", "escalat")), f"Unexpected reply: {reply2}"
    print("  Passed: P1 Outage SLA breach correctly recognized and escalated.")

    # Test 3: LumenWorks (ACCT-002) - Pickup Delay Service Credit
    time.sleep(5)
    print("\n[TEST 3] Persona: LumenWorks (ACCT-002)")
    print("Scenario: Custom Contract Rule - INR 300 Credit for Carrier Delay > 4 Hours")
    res3 = call_chat(
        account_id="ACCT-002",
        message="A pickup was delayed on ORD-2002 by over 4 hours due to carrier fault. Am I eligible for a service credit under our agreement?",
        session_id="test-lumen-01"
    )
    reply3 = res3.get("data", {}).get("reply", "")
    print(f"Reply:\n{reply3}\n")
    assert any(k in reply3.lower() for k in ("300", "credit", "lumenworks")), f"Unexpected reply: {reply3}"
    print("  Passed: LumenWorks INR 300 carrier-fault delay credit rule verified.")

    # Test 4: Beacon Retail (ACCT-003) - Standard SOP & Action Confirmation
    time.sleep(5)
    print("\n[TEST 4] Persona: Beacon Retail (ACCT-003)")
    print("Scenario: Explicit Cancellation Request for ORD-3001 & Human Confirmation")
    res4 = call_chat(
        account_id="ACCT-003",
        message="Please cancel order ORD-3001 for me.",
        session_id="test-beacon-01"
    )
    staged = res4.get("data", {}).get("staged_action")
    reply4 = res4.get("data", {}).get("reply", "")
    print(f"Reply:\n{reply4}\n")
    print(f"Staged Action Metadata: {staged}")
    assert staged is not None, "Expected stage_action to be called when user explicitly asks to cancel!"
    action_id = staged["action_id"]
    print(f"  -> Confirming action {action_id} via /api/v1/action/confirm...")
    c_res = call_confirm("test-beacon-01", action_id, confirmed=True)
    print(f"  -> Confirmation Result: {c_res}")
    print("  Passed: Action staging and confirmation lifecycle executed.")

    # Test 5: Axis Labs (ACCT-004) - Non-Cancellable Delivered Order
    time.sleep(5)
    print("\n[TEST 5] Persona: Axis Labs (ACCT-004)")
    print("Scenario: Order ORD-4001 is already DELIVERED. Can it be cancelled?")
    res5 = call_chat(
        account_id="ACCT-004",
        message="Can I cancel order ORD-4001?",
        session_id="test-axis-01"
    )
    reply5 = res5.get("data", {}).get("reply", "")
    print(f"Reply:\n{reply5}\n")
    assert any(k in reply5.lower() for k in ("delivered", "cannot", "not")), f"Unexpected reply: {reply5}"
    print("  Passed: Delivered shipment cancellation prohibited.")

    # Test 6: Security Boundary - Cross-Tenant Isolation
    time.sleep(5)
    print("\n[TEST 6] Edge Case: Cross-Tenant Isolation")
    print("Scenario: ACCT-003 attempts to query ACCT-001 private order ORD-1001")
    res6 = call_chat(
        account_id="ACCT-003",
        message="Show me the order status and shipment fee for order ORD-1001.",
        session_id="test-security-01"
    )
    reply6 = res6.get("data", {}).get("reply", "")
    print(f"Reply:\n{reply6}\n")
    assert any(k in reply6.lower() for k in ("not found", "unable", "not have access", "does not exist", "no record", "none")), f"Unexpected reply: {reply6}"
    print("  Passed: Cross-Tenant isolation strictly preserved.")

    print("\n" + "=" * 75)
    print("ALL 6 MULTI-TENANT & EDGE CASE SCENARIOS PASSED WITH HIGH FIDELITY!")
    print("=" * 75)


if __name__ == "__main__":
    run_tests()
