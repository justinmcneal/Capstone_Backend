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
