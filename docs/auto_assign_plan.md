# Auto-Assign Feature Integration Plan

## Backend Confirmation
Yes! There is an existing `auto_assign_application` service on the backend (`loans/services/assignment.py`). This service automatically determines the best Loan Officer for a pending application based on workload, capacity, and potentially specialization criteria.

## UI Implementation Plan

If we decide to expose this feature on the Admin frontend, here is how we would integrate it seamlessly into the new Tabbed layout:

### 1. Auto-Assign Global Toggle
**Location:** Inside the "Settings" page or as a quick-toggle in the "Overview" tab of the Applications page.
**Functionality:** 
- Allow Super Admins to turn ON "Automatic Assignment" globally. 
- When enabled, new applications submitted by customers will bypass the "Unassigned Queue" entirely and be automatically routed to the optimal Loan Officer by the backend upon submission.

### 2. Bulk Auto-Assign Action
**Location:** Inside the "Unassigned" tab of the Applications page.
**Functionality:**
- Add a "Bulk Auto-Assign" button above the Unassigned table.
- Clicking this button would trigger a backend endpoint that loops through all pending applications and runs the `auto_assign_application` function for each, clearing out the Unassigned backlog instantly.

### 3. Single Auto-Assign Button
**Location:** Next to the manual "Assign App" button.
**Functionality:**
- When manually viewing an Unassigned Application, instead of explicitly picking an officer from the dropdown, the Admin can click a "Magic Assign" or "Auto-Assign" button. The backend will choose the best officer and assign the application immediately.

### Next Steps
Since you only requested a plan for now, these features have **not** been implemented in the UI. When you are ready to activate auto-assignment, we can implement the necessary backend endpoints (e.g., `POST /api/loans/admin/auto-assign-bulk/`) and connect them to the frontend toggles!
