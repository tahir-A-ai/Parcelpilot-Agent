# ParcelPilot Project Specification & Business Logic

## 1. Reference Snapshot Time
- Reference Datetime: `2026-08-16 11:00 Asia/Kolkata`. All time differences and SLA calculations must use this base.

## 2. Source Precedence Hierarchy
When conflicting information arises, resolve in the following strict order:
1. Signed Customer Service Agreement (e.g., Northstar, LumenWorks).
2. Current Support Policy & Cancellation SOP (`01_Support_Policy_v3_CURRENT.pdf`, `03_Cancellation_and_Service_Credit_SOP_v4.pdf`).
3. Product Operations Guide & Known Issues (`04_Product_Operations_Guide_and_Known_Issues.pdf`).
4. Deprecated Files (`02_Support_Policy_v2_DEPRECATED.pdf`): NEVER USE.
5. Historical Tickets: Context only; may contain erroneous resolutions.

## 3. Core Business Logic Rules
- Northstar Logistics (ACCT-001):
  - Free cancellation for any BOOKED shipment prior to pickup.
  - P1 Response SLA: 15 minutes, 24x7. Monthly credit cap: INR 5,000.
- LumenWorks (ACCT-002):
  - Fixed INR 300 credit if carrier-caused pickup delay > 4 hours.
  - Standard cancellation SOP applies.
- Default Cancellation SOP (ACCT-003 / Beacon Retail):
  - DRAFT: Free cancellation.
  - BOOKED (<30 mins from booking): Free cancellation.
  - BOOKED (>30 mins from booking): INR 250 fee.
  - PICKED_UP / DELIVERED: Non-cancellable; trigger return-to-origin.
- High-Value Safeguard: Any credit > INR 1,000 requires explicit manager escalation.