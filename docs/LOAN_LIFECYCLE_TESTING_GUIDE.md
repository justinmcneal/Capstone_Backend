# Loan Lifecycle Testing Guide

Merged documentation for loan module testing, assignment workflows, disbursement, repayment schedules, payment recording, and remaining endpoints.

## Wave

- Wave: 3
- Status: Done

## Navigation

1. [Loan Module API Testing Guide](#section-1-loans_testing_guidemd)
2. [Officer Assignment Testing Guide](#section-2-officer_assignment_testing_guidemd)
3. [P3.A8 Assign Application Testing Guide](#section-3-assignment_testing_flowmd)
4. [Loan Disbursement Testing Guide](#section-4-disbursement_testing_guidemd)
5. [Repayment Schedule Testing Guide](#section-5-repayment_schedule_testing_guidemd)
6. [Loan Payment Recording Testing Guide](#section-6-payment_recording_testing_guidemd)
7. [Remaining Features Testing Guide](#section-7-remaining_features_testing_guidemd)

## Source Files

1. `LOANS_TESTING_GUIDE.md`
2. `OFFICER_ASSIGNMENT_TESTING_GUIDE.md`
3. `ASSIGNMENT_TESTING_FLOW.md`
4. `DISBURSEMENT_TESTING_GUIDE.md`
5. `REPAYMENT_SCHEDULE_TESTING_GUIDE.md`
6. `PAYMENT_RECORDING_TESTING_GUIDE.md`
7. `REMAINING_FEATURES_TESTING_GUIDE.md`

---

## Section 1: LOANS_TESTING_GUIDE.md

# Loan Module API Testing Guide

Complete guide to test loan endpoints.

---

## Setup

**Base URL:** `http://localhost:8000/api/loans`

---

## Customer Endpoints

### 1. List Loan Products

```
GET /api/loans/products/
```

**Headers:** `Authorization: Bearer <customer_access_token>`

---

### 2. Get Product Details

```
GET /api/loans/products/<product_id>/
```

---

### 3. Pre-Qualify (AI Assessment)

```
POST /api/loans/pre-qualify/
```

**Body:**
```json
{
    "product_id": "...",
    "amount": 25000,
    "term_months": 12,
    "purpose": "Expand inventory"
}
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "eligible": true,
        "eligibility_score": 72,
        "risk_category": "medium",
        "recommended_amount": 20000,
        "strengths": ["Has bank account", "Good payment history"],
        "concerns": ["Limited business history"],
        "can_apply": true
    }
}
```

---

### 4. Submit Application

```
POST /api/loans/apply/
```

**Body:**
```json
{
    "product_id": "...",
    "requested_amount": 25000,
    "term_months": 12,
    "purpose": "Business expansion"
}
```

---

### 5. List My Applications

```
GET /api/loans/applications/
```

---

### 6. Get Application Status

```
GET /api/loans/applications/<application_id>/
```

---

## Admin Endpoints (Product Management)

### 7. List All Products

```
GET /api/loans/admin/products/
```

**Headers:** `Authorization: Bearer <admin_access_token>`

---

### 8. Create Loan Product

```
POST /api/loans/admin/products/
```

**Body:**
```json
{
    "name": "Micro Business Loan",
    "code": "MBL001",
    "description": "For small business needs",
    "min_amount": 5000,
    "max_amount": 50000,
    "interest_rate": 0.015,
    "min_term_months": 3,
    "max_term_months": 24,
    "required_documents": ["valid_id"],
    "min_business_months": 6,
    "min_monthly_income": 5000
}
```

---

### 9. Update Product

```
PUT /api/loans/admin/products/<product_id>/
```

---

### 10. Deactivate Product

```
DELETE /api/loans/admin/products/<product_id>/
```

---

## Loan Officer Endpoints

### 11. List Pending Applications

```
GET /api/loans/officer/applications/
GET /api/loans/officer/applications/?status=pending
GET /api/loans/officer/applications/?status=mine
```

**Headers:** `Authorization: Bearer <loan_officer_access_token>`

---

### 12. View Application Details

```
GET /api/loans/officer/applications/<application_id>/
```

---

### 13. Approve Application

```
PUT /api/loans/officer/applications/<application_id>/review/
```

**Body:**
```json
{
    "action": "approve",
    "approved_amount": 20000,
    "notes": "Good business profile"
}
```

---

### 14. Reject Application

```
PUT /api/loans/officer/applications/<application_id>/review/
```

**Body:**
```json
{
    "action": "reject",
    "rejection_reason": "Incomplete documentation",
    "notes": "Missing business permit"
}
```

---

## Testing Flow

1. **Admin:** Create loan product
2. **Customer:** View products
3. **Customer:** Complete profile + upload documents
4. **Customer:** Pre-qualify (AI assessment)
5. **Customer:** Submit application
6. **Loan Officer:** Review applications
7. **Loan Officer:** Approve/reject
8. **Customer:** Check application status

---

## Section 2: OFFICER_ASSIGNMENT_TESTING_GUIDE.md

# Officer Assignment Testing Guide

## Overview

Assign loan applications to officers for review.

---

## Endpoints

### 1. Manual Assignment (Admin)
```
POST /api/loans/admin/applications/<id>/assign/
Authorization: Bearer <admin_token>
Content-Type: application/json

{
    "officer_id": "<officer_id>"
}
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "application_id": "abc123",
        "assigned_officer": "def456",
        "officer_name": "John Doe",
        "status": "under_review"
    },
    "message": "Application assigned successfully"
}
```

---

### 2. View Officer Workloads (Admin)
```
GET /api/loans/admin/officers/workload/
Authorization: Bearer <admin_token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "officers": [
            {
                "id": "def456",
                "employee_id": "EMP001",
                "name": "John Doe",
                "pending_count": 5,
                "active": true
            }
        ],
        "total": 1
    }
}
```

---

## Auto-Assignment

On loan submission, applications are automatically assigned to the officer with fewest pending applications. Officer receives email notification.

---

## Section 3: ASSIGNMENT_TESTING_FLOW.md

# P3.A8 - Assign Application Testing Guide

Complete step-by-step guide to test the application assignment flow in Insomnia/Postman.

---

## Overview

This guide walks you through:
1. Creating a customer account
2. Creating a loan product (as admin)
3. Customer submitting a loan application
4. Admin assigning the application to a loan officer

---

## Prerequisites

Ensure your backend server is running:
```bash
cd backend
source venv/bin/activate
python manage.py runserver
```

**Base URL:** `http://localhost:8000`

---

## Step 1: Create Admin (First Time Only)

If you don't have an admin account yet, create one via terminal:

```bash
cd backend
source venv/bin/activate
python manage.py create_admin --username admin --email admin@system.com --password AdminPass123! --super-admin
```

---

## Step 2: Login as Admin

**Endpoint:** `POST /api/auth/admin/login/`

**Body:**
```json
{
    "username": "admin",
    "password": "AdminPass123!"
}
```

**Response:**
```json
{
    "status": "success",
    "message": "Admin logged in successfully",
    "data": {
        "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
        "admin": {
            "id": "...",
            "username": "admin",
            "email": "admin@system.com",
            "role": "admin"
        }
    }
}
```

**Save the `access` token** - you'll need it for admin operations.

---

## Step 3: Create a Loan Officer

**Endpoint:** `POST /api/auth/admin/loan-officers/`

**Headers:**
```
Authorization: Bearer <admin_access_token>
Content-Type: application/json
```

**Body:**
```json
{
    "first_name": "Maria",
    "last_name": "Santos",
    "email": "maria.officer@example.com",
    "phone": "09181234567",
    "username": "maria.santos",
    "password": "OfficerPass123!"
}
```

**Response:**
```json
{
    "status": "success",
    "message": "Loan officer created successfully",
    "data": {
        "officer_id": "67980b8cc4d5e8c3a1234567",
        "username": "maria.santos",
        "full_name": "Maria Santos",
        "email": "maria.officer@example.com"
    }
}
```

**Save the `officer_id`** - you'll need it for assignment later.

---

## Step 4: Create a Loan Product

**Endpoint:** `POST /api/loans/admin/products/`

**Headers:**
```
Authorization: Bearer <admin_access_token>
Content-Type: application/json
```

**Body:**
```json
{
    "name": "Micro Business Loan",
    "code": "MBL001",
    "description": "For small business needs",
    "min_amount": 5000,
    "max_amount": 50000,
    "interest_rate": 0.015,
    "min_term_months": 3,
    "max_term_months": 24,
    "required_documents": ["valid_id", "business_permit"],
    "min_business_months": 6,
    "min_monthly_income": 5000
}
```

**Response:**
```json
{
    "status": "success",
    "message": "Product created successfully",
    "data": {
        "id": "67980c1ac4d5e8c3a1234568",
        "code": "MBL001",
        "name": "Micro Business Loan"
    }
}
```

**Save the `id` (product_id)** - customers will need this to apply.

**Important:** Make sure the product is **active** (active: true). If you get "Loan product not found" error later, activate it with:

```
PUT /api/loans/admin/products/<product_id>/
Body: { "active": true }
```

---

## Step 5: Create a Customer Account

**Endpoint:** `POST /api/auth/signup/`

**Body:**
```json
{
    "first_name": "Juan",
    "last_name": "Dela Cruz",
    "email": "juan@example.com",
    "password": "SecurePass123!",
    "password_confirm": "SecurePass123!",
    "phone": "09171234567",
    "language": "tl"
}
```

**Response:**
```json
{
    "status": "success",
    "message": "Account created. Please verify your email.",
    "data": {
        "email": "juan@example.com"
    }
}
```

---

## Step 6: Verify Customer Email

**Endpoint:** `POST /api/auth/verify-email/`

**Body:**
```json
{
    "email": "juan@example.com",
    "otp": "123456"
}
```

**Note:** Check your terminal/logs for the OTP code, or use `123456` if in development mode.

**Response:**
```json
{
    "status": "success",
    "message": "Email verified successfully",
    "data": {
        "customer_id": "67980c2ac4d5e8c3a1234569",
        "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
    }
}
```

**Save the `access` token** - you'll need it for customer operations.

---

## Step 7: Customer Login

**Endpoint:** `POST /api/auth/login/`

**Body:**
```json
{
    "email": "juan@example.com",
    "password": "SecurePass123!"
}
```

**Response:**
```json
{
    "status": "success",
    "message": "Login successful",
    "data": {
        "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
        "customer": {
            "customer_id": "67980c2ac4d5e8c3a1234569",
            "email": "juan@example.com",
            "first_name": "Juan",
            "last_name": "Dela Cruz"
        }
    }
}
```

---

## Step 7A: Complete Personal Profile (as Customer)

**Before applying for a loan, customers must complete their personal profile.**

**Endpoint:** `PUT /api/profile/`

**Headers:**
```
Authorization: Bearer <customer_access_token>
Content-Type: application/json
```

**Body:**
```json
{
    "date_of_birth": "1990-05-15",
    "gender": "male",
    "civil_status": "married",
    "nationality": "Filipino",
    "address_line1": "123 Sample Street",
    "address_line2": "Unit 5B",
    "barangay": "Poblacion",
    "city_municipality": "Makati",
    "province": "Metro Manila",
    "zip_code": "1234",
    "emergency_contact_name": "Maria Cruz",
    "emergency_contact_phone": "09171234567",
    "emergency_contact_relationship": "Spouse"
}
```

**Response:**
```json
{
    "status": "success",
    "message": "Personal profile updated successfully",
    "data": {
        "id": "...",
        "profile_completed": true,
        "completion_percentage": 100
    }
}
```

---

## Step 7B: Complete Business Profile (as Customer)

**Endpoint:** `PUT /api/profile/business/`

**Headers:**
```
Authorization: Bearer <customer_access_token>
Content-Type: application/json
```

**Body:**
```json
{
    "business_name": "Juan's Sari-Sari Store",
    "business_type": "sari_sari_store",
    "business_description": "Neighborhood convenience store selling daily essentials",
    "business_address": "123 Market Road",
    "business_barangay": "Poblacion",
    "business_city": "Makati",
    "business_province": "Metro Manila",
    "years_in_operation": 3.5,
    "is_registered": true,
    "registration_type": "DTI",
    "registration_number": "DTI-12345678",
    "estimated_monthly_income": 15000,
    "income_range": "10000_20000",
    "estimated_monthly_expenses": 8000,
    "number_of_employees": 1
}
```

**Response:**
```json
{
    "status": "success",
    "message": "Business profile updated successfully",
    "data": {
        "id": "...",
        "business_name": "Juan's Sari-Sari Store",
        "profile_completed": true
    }
}
```

---

## Step 8: Submit Loan Application (as Customer)

**Endpoint:** `POST /api/loans/apply/`

**Headers:**
```
Authorization: Bearer <customer_access_token>
Content-Type: application/json
```

**Body:**
```json
{
    "product_id": "697b67963a9a98a35ac9789d",
    "requested_amount": 25000,
    "term_months": 12,
    "purpose": "Business expansion - buying new equipment"
}
```

**Note:** The `product_id` is the `_id` field from the MongoDB product document.

**Response:**
```json
{
    "status": "success",
    "message": "Application submitted successfully",
    "data": {
        "application_id": "67980c3ac4d5e8c3a1234570",
        "status": "pending",
        "requested_amount": 25000,
        "term_months": 12
    }
}
```

**Save the `application_id`** - you'll need this for assignment!

---

## Step 9: Check Officer Workload (Optional)

Before assigning, you can check which officers are available:

**Endpoint:** `GET /api/loans/admin/officers/workload/`

**Headers:**
```
Authorization: Bearer <admin_access_token>
```

**Response:**
```json
{
    "status": "success",
    "message": "Officer workload retrieved",
    "data": {
        "officers": [
            {
                "officer_id": "67980b8cc4d5e8c3a1234567",
                "full_name": "Maria Santos",
                "pending_count": 0,
                "in_review_count": 0,
                "total_active": 0
            }
        ],
        "total": 1
    }
}
```

---

## Step 10: 🎯 Assign Application to Officer (TEST TARGET)

**Endpoint:** `POST /api/loans/admin/applications/<application_id>/assign/`

**URL Example:** `POST /api/loans/admin/applications/67980c3ac4d5e8c3a1234570/assign/`

**Headers:**
```
Authorization: Bearer <admin_access_token>
Content-Type: application/json
```

**Body:**
```json
{
    "officer_id": "67980b8cc4d5e8c3a1234567"
}
```

**Expected Response (Success):**
```json
{
    "status": "success",
    "message": "Application assigned successfully",
    "data": {
        "application_id": "67980c3ac4d5e8c3a1234570",
        "assigned_officer": "67980b8cc4d5e8c3a1234567",
        "officer_name": "Maria Santos",
        "status": "under_review"
    }
}
```

---

## Step 11: Verify Assignment (Optional)

You can verify the assignment from different perspectives:

### As Admin - Check Officer Workload Again

**Endpoint:** `GET /api/loans/admin/officers/workload/`

You should see the officer now has 1 application in review.

### As Officer - List My Applications

**Login as Officer First:**

**Endpoint:** `POST /api/auth/loan-officer/login/`

**Body:**
```json
{
    "username": "maria.santos",
    "password": "OfficerPass123!"
}
```

**Then Check Applications:**

**Endpoint:** `GET /api/loans/officer/applications/?status=mine`

**Headers:**
```
Authorization: Bearer <officer_access_token>
```

You should see the assigned application in the list.

### As Customer - Check Application Status

**Endpoint:** `GET /api/loans/applications/<application_id>/`

**Headers:**
```
Authorization: Bearer <customer_access_token>
```

You should see the application status is now `under_review`.

---

## Error Cases to Test

### 1. Invalid Officer ID

**Body:**
```json
{
    "officer_id": "invalid_id"
}
```

**Expected Response (404):**
```json
{
    "status": "error",
    "message": "Officer not found"
}
```

### 2. Missing Officer ID

**Body:**
```json
{}
```

**Expected Response (400):**
```json
{
    "status": "error",
    "message": "officer_id is required"
}
```

### 3. Invalid Application ID

**URL:** `POST /api/loans/admin/applications/invalid_id/assign/`

**Expected Response (404):**
```json
{
    "status": "error",
    "message": "Application not found"
}
```

### 4. Unauthorized Access (No Admin Token)

**Expected Response (403):**
```json
{
    "status": "error",
    "message": "Admin access required"
}
```

---

## Quick Reference

| Step | Endpoint | User | Key Data |
|------|----------|------|----------|
| 1 | POST /api/auth/admin/login/ | Admin | Get admin token |
| 2 | POST /api/auth/admin/loan-officers/ | Admin | Get officer_id |
| 3 | POST /api/loans/admin/products/ | Admin | Get product_id |
| 4 | POST /api/auth/signup/ | Customer | Create account |
| 5 | POST /api/auth/verify-email/ | Customer | Verify + get token |
| 6 | PUT /api/profile/ | Customer | Complete personal profile |
| 7 | PUT /api/profile/business/ | Customer | Complete business profile |
| 8 | POST /api/loans/apply/ | Customer | Get application_id |
| 9 | POST /api/loans/admin/applications/{id}/assign/ | Admin | ✅ Assignment |

---

## Troubleshooting

### "Admin access required"
- Make sure you're using the admin access token
- Verify the token is in the `Authorization: Bearer <token>` header

### "Application not found"
- Double-check the application_id from step 8
- Ensure you're using the full MongoDB ObjectId

### "Officer not found"
- Verify the officer_id from step 3
- Make sure the officer account was created successfully

### "Invalid token"
- Tokens may expire - login again to get a fresh token
- Ensure no extra spaces in the Authorization header

### "Loan product not found"
- Check if the product is active: `"active": true` in the database
- Inactive products cannot receive new applications
- Activate it: `PUT /api/loans/admin/products/<id>/` with `{"active": true}`

### "Cannot apply - requirements not met"
- Customer must complete both **personal** and **business** profiles before applying
- Complete personal profile: `PUT /api/profile/`
- Complete business profile: `PUT /api/profile/business/`
- Check completion status: `GET /api/profile/summary/`

---

## Success Criteria ✅

For P3.A8 to pass, you should see:

1. ✅ 200 status code response
2. ✅ Success message: "Application assigned successfully"
3. ✅ Response contains:
   - `application_id`
   - `assigned_officer` (officer ID)
   - `officer_name`
   - `status: "under_review"`
4. ✅ Officer can now see the application in their list
5. ✅ Officer workload count increases by 1

---

## Notes

- All IDs are MongoDB ObjectIds (24-character hex strings)
- Tokens typically expire after 1 hour - refresh if needed
- Assignment can only be done by admin users
- Applications must be in `pending` status to be assigned
- You can reassign applications to different officers if needed

---

## Section 4: DISBURSEMENT_TESTING_GUIDE.md

# Loan Disbursement Testing Guide

## Overview

Mark approved loans as disbursed and notify customers.

---

## Endpoint

```
POST /api/loans/officer/applications/<id>/disburse/
Authorization: Bearer <officer_token>
Content-Type: application/json

{
    "amount": 25000,
    "method": "bank_transfer",
    "reference": "TXN-2026-001234"
}
```

---

## Request Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `amount` | No | approved_amount | Disbursed amount |
| `method` | No | bank_transfer | Method: bank_transfer, cash, etc. |
| `reference` | **Yes** | - | Transaction reference number |

---

## Response

```json
{
    "status": "success",
    "data": {
        "id": "abc123",
        "status": "disbursed",
        "disbursed_amount": 25000,
        "disbursement_method": "bank_transfer",
        "disbursement_reference": "TXN-2026-001234",
        "disbursed_at": "2026-01-07T11:18:00Z"
    },
    "message": "Loan disbursed successfully"
}
```

---

## Validation

- Only **approved** loans can be disbursed
- `reference` is required
- Officer/Admin authentication required

---

## Email Notification

Customer receives email with:
- Disbursed amount
- Disbursement method
- Reference number

---

## Section 5: REPAYMENT_SCHEDULE_TESTING_GUIDE.md

# Repayment Schedule Testing Guide

## Overview

View payment schedule for disbursed loans.

---

## How It Works

1. Loan officer disburses loan → Schedule auto-generated
2. Customer views schedule via API

---

## Customer Endpoint

```
GET /api/loans/applications/<id>/schedule/
Authorization: Bearer <customer_token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "loan_id": "abc123",
        "principal": 25000,
        "interest_rate": 0.015,
        "term_months": 12,
        "monthly_payment": 2458.33,
        "total_amount": 29500,
        "total_interest": 4500,
        "paid_count": 0,
        "remaining_balance": 29500,
        "next_payment": {
            "number": 1,
            "due_date": "2026-02-12",
            "total_amount": 2458.33
        },
        "installments": [
            {
                "number": 1,
                "due_date": "2026-02-12",
                "principal": 2083.33,
                "interest": 375.00,
                "total_amount": 2458.33,
                "status": "pending"
            }
        ]
    }
}
```

---

## Calculation

**Simple Interest:**
- Monthly Interest = Principal × Interest Rate
- Monthly Payment = (Principal / Term) + Monthly Interest
- Total = Principal + (Monthly Interest × Term)

**Example (₱25,000 at 1.5%/month for 12 months):**
- Monthly Interest: ₱25,000 × 0.015 = ₱375
- Monthly Principal: ₱25,000 / 12 = ₱2,083.33
- Monthly Payment: ₱2,458.33
- Total Interest: ₱4,500
- Total: ₱29,500

---

## Validation

- Only disbursed loans have schedules
- Customer can only view their own schedules

---

## Section 6: PAYMENT_RECORDING_TESTING_GUIDE.md

# Loan Payment Recording Testing Guide

## Overview

Record customer payments against repayment schedules.

---

## Endpoints

### 1. Record Payment (Officer)
```
POST /api/loans/officer/payments/
Authorization: Bearer <officer_token>
Content-Type: application/json

{
    "loan_id": "abc123",
    "installment_number": 1,
    "amount": 2500,
    "payment_method": "cash",
    "reference": "REC-2026-001"
}
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "payment_id": "xyz789",
        "loan_id": "abc123",
        "installment_number": 1,
        "amount": 2500,
        "installment_status": "paid",
        "remaining_balance": 27000
    },
    "message": "Payment recorded successfully"
}
```

---

### 2. View Payment History (Customer)
```
GET /api/loans/applications/<id>/payments/
Authorization: Bearer <customer_token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "payments": [
            {
                "id": "xyz789",
                "amount": 2500,
                "installment_number": 1,
                "payment_method": "cash",
                "reference": "REC-2026-001",
                "recorded_at": "2026-01-12T08:50:00Z"
            }
        ],
        "total_paid": 2500,
        "count": 1
    }
}
```

---

## Payment Methods

- `cash`
- `bank_transfer`
- `gcash`
- `maya`
- `other`

---

## Auto-Update Schedule

When payment recorded:
- Full payment → installment status = `paid`
- Partial payment → installment status = `partial`

---

## Section 7: REMAINING_FEATURES_TESTING_GUIDE.md

# Remaining Features Testing Guide

## New Endpoints Summary

### 1. Application Resubmission
```
POST /api/loans/applications/<id>/resubmit/
Authorization: Bearer <customer_token>
```
- Only works for `rejected` applications
- Resets status to `draft`

---

### 2. Rejection Feedback
```
GET /api/loans/applications/<id>/feedback/
Authorization: Bearer <customer_token>
```
- AI explains rejection reason
- Includes improvement suggestions

---

### 3. Document Re-upload Request (Officer)
```
POST /api/documents/<id>/request-reupload/
Authorization: Bearer <officer_token>
Content-Type: application/json

{"reason": "Image is blurry, please upload a clearer photo"}
```

---

### 4. Loan Education
```
GET /api/ai/education/
GET /api/ai/education/<topic>/
```
Topics: `what_is_a_loan`, `interest_rates`, `loan_process`, `documents_needed`, `improving_chances`

---

### 5. FAQs
```
GET /api/ai/faqs/
```

---

### 6. Health Check
```
GET /api/health/
```
Returns: MongoDB status, AI status

---

### 7. Notification Preferences
```
GET /api/profile/notifications/
PUT /api/profile/notifications/

Body:
{
    "preferences": {
        "email_loan_updates": true,
        "email_payment_reminders": true,
        "email_promotions": false
    }
}
```

---

### 8. Multilingual Support
Customer model has `language` field (`en` or `tl`). AI responses adapt based on language.

---

## All Features Complete! 🎉
