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
