3. FUNCTIONAL TEST CASES
TC-001 — Search: Valid Customer Name

Input: "Gab Soriano"
Expected: Customer card loads with correct name, phone, loan type, balances, and due date
Pass criteria: All fields match database record
fix: when search gab soriano nothing found but when input gab and soriano it will show "gab soriano" but when gab soriano combine in the search bar it is says no active loan found

TC-002 — Search: Valid Phone Number

Input: "09476935829"
Expected: Same customer loads correctly
Pass criteria: Identical result to TC-001
Working

TC-003 — Search: Valid Customer ID

Input: Known customer ID from seed data
Expected: Customer loads correctly
Pass criteria: Correct customer card displayed
working
TC-004 — Search: Valid Loan ID

Input: Known loan ID from seed data
Expected: Loan loads with correct repayment schedule
Pass criteria: Installment table populated correctly
working

TC-005 — Search: Invalid Input

Input: "xxxxxxxxxxx"
Expected: No results found message displayed
Pass criteria: No crash, no empty broken UI, friendly error shown
working
TC-006 — Search: Product ID (should be blocked)

Input: Known product ID
Expected: No result, tip message confirms product ID is not supported
Pass criteria: System does not return a match
working 

TC-007 — Change Customer

Steps: Load a customer, click "Change"
Expected: Search field clears, customer card resets, form resets
Pass criteria: No residual data from previous customer remains
working

TC-008 — Repayment Schedule Loads Correctly

Expected: 3 installments shown, each ₱7,166.67, all Pending, correct due dates
Pass criteria: Matches loan terms exactly
working 

TC-009 — Apply Penalty on Installment #1

Steps: Click "Apply Penalty" on row 1
Expected: Penalty amount is added, status or penalty column updates, confirmation shown
Pass criteria: Database reflects penalty, UI updates without page reload
not working
TC-010 — Apply Penalty Multiple Times (Edge Case)

Steps: Click "Apply Penalty" on same installment rapidly 3 times
Expected: Penalty applied only once or system prevents duplicate
Pass criteria: No duplicate penalty entries in database or UI

working
TC-011 — Installment # Auto-fill

Expected: On load, Installment # defaults to 1, Amount auto-fills to ₱7,166.67
Pass criteria: Fields pre-populated correctly
working
TC-012 — Change Installment Number

Steps: Change Installment # to 2
Expected: Amount updates to ₱7,166.67 for installment 2
Pass criteria: Correct installment data loads
working
TC-013 — "Due" Button

Steps: Click "Due"
Expected: Amount field fills with exact installment due amount
Pass criteria: Amount matches schedule row
working
TC-014 — "Full" Button
working
Steps: Click "Full"
Expected: Amount field fills with total remaining balance (₱21,500)
Pass criteria: Amount matches remaining balance shown in customer card
working 
TC-015 — Payment Method: Cash

Steps: Select "Cash", submit payment
Expected: Payment recorded successfully
Pass criteria: Confirmation shown, history updated
working
TC-016 — Payment Method: Check

Steps: Select "Check", submit payment
Expected: Payment recorded successfully
Pass criteria: Confirmation shown, history updated
working 
TC-017 — Payment Method Restriction

Expected: Only Cash and Check are available options in dropdown
Pass criteria: No other payment methods present
working

TC-018 — Submit Empty Amount

Steps: Clear amount field, attempt to submit
Expected: Validation error shown, submission blocked
Pass criteria: No API call fired, error message displayed
working 
TC-019 — Submit Zero Amount

Steps: Enter 0 in amount field, attempt to submit
Expected: Validation error shown
Pass criteria: Submission blocked, error message displayed
working
TC-020 — Submit Overpayment

Steps: Enter amount greater than ₱21,500, attempt to submit
Expected: Validation error or warning shown
Pass criteria: System prevents or warns on overpayment
working 
TC-021 — Successful Payment Flow (End-to-End)

Steps: Search customer → verify schedule → enter installment 1 → select Cash → submit
Expected:

Installment 1 status changes from Pending to Paid
Repayment progress updates to "1 of 3 paid"
Payment History shows new entry with correct date, amount, method
Remaining balance decreases from ₱21,500 to ₱14,333.33


Pass criteria: All of the above reflected in UI and confirmed in database