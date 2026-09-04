import asyncio
import sqlite3
import os
from fastapi.testclient import TestClient

from app.main import app
from app.core.config.settings import get_settings

def run_e2e_test():
    client = TestClient(app)
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'parcelpilot.db')
    
    print("=== Phase 4 E2E Backend Test ===")
    
    with client:
        # Step 1: Query the agent
        print("\n[1/4] Sending chat message to cancel ORD-1001...")
        chat_payload = {
            "account_id": "ACCT-001",
            "message": "I need to cancel order ORD-1001. Can you prepare that action for me please?",
            "session_id": "sess-e2e-12345"
        }
        
        # This will take some time as it hits the LLM
        response = client.post("/api/v1/chat", json=chat_payload)
        assert response.status_code == 200, f"Chat failed: {response.text}"
        
        reply = response.json().get("data", {}).get("reply")
        print("\nAgent Reply:")
        print(reply)
        
        # Step 2: Check SQLite for the staged action
        print("\n[2/4] Verifying staged action in database...")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute(
            "SELECT * FROM staged_actions WHERE session_id = 'sess-e2e-12345' AND status = 'AWAITING_CONFIRMATION' ORDER BY created_at DESC LIMIT 1"
        )
        action_row = cur.fetchone()
        
        if not action_row:
            print("Failed: No staged action was created by the agent.")
            print("This could be because the agent didn't invoke the stage_action tool, or the LLM failed to understand the prompt.")
            return
            
        action_id = action_row["action_id"]
        print(f"Found staged action: {action_id} (Type: {action_row['action_type']})")
        print(f"Payload JSON: {action_row['payload_json']}")
        
        # Step 3: Confirm the action
        print(f"\n[3/4] Sending confirmation for {action_id}...")
        confirm_payload = {
            "session_id": "sess-e2e-12345",
            "action_id": action_id,
            "confirmed": True
        }
        
        response = client.post("/api/v1/action/confirm", json=confirm_payload)
        assert response.status_code == 200, f"Confirm failed: {response.text}"
        print(f"Confirmation Response: {response.json()['data']['message']}")
        
        # Step 4: Verify the operational DB update (order status)
        print("\n[4/4] Verifying order status was updated in DB...")
        cur.execute("SELECT status FROM orders WHERE order_id = 'ORD-1001'")
        order_status = cur.fetchone()["status"]
        
        if order_status == "CANCELLED":
            print(f"Success! Order ORD-1001 status is now {order_status}.")
        else:
            print(f"Failed: Order status is {order_status}, expected CANCELLED.")
            
if __name__ == "__main__":
    run_e2e_test()
