# Profile Module Documentation

> User profile management for MSME Pathways - personal data, business information, and alternative credit data collection.

---

## Overview

The Profile module collects and manages user data needed for loan pre-qualification:

```
┌─────────────────────────────────────────────────────────────┐
│                    PROFILE DATA FLOW                         │
├─────────────────────────────────────────────────────────────┤
│ Customer Login → Personal Profile → Business Profile        │
│                                            ↓                 │
│                               Alternative Data Collection    │
│                                            ↓                 │
│                               Ready for Loan Pre-Qualification│
└─────────────────────────────────────────────────────────────┘
```

---

## Profile Types

### 1. Personal Profile (CustomerProfile)

Personal information for identity verification and contact.

**Fields:**
- Date of birth, gender, civil status
- Complete address (barangay, city, province)
- Emergency contact information
- Profile completion tracking

---

### 2. Business Profile (BusinessProfile)

MSME/business information for loan assessment.

**Fields:**
- Business name, type, description
- Business location
- Years in operation
- Registration status (DTI/SEC/BIR)
- Estimated monthly income/expenses
- Number of employees

**Business Types:**
- `sari_sari_store` - Sari-sari store
- `market_vendor` - Market vendor/stallholder
- `home_based_seller` - Home-based seller
- `food_vendor` - Food vendor/eatery
- `transport_service` - Tricycle/jeepney operator
- `freelancer` - Freelance services
- `agriculture` - Small-scale farming
- `manufacturing` - Small manufacturing
- `retail_trade` - Retail trade
- `other` - Other

---

### 3. Alternative Data (AlternativeData)

Alternative credit data for users with no formal credit history.

**Categories:**
- Education & Employment
- Housing status
- Existing loans/credit
- Digital footprint (bank account, e-wallet usage)
- Utility payment history
- Social capital (coop membership)

---

## API Endpoints

### Personal Profile

```http
GET /api/profile/
Authorization: Bearer <access_token>
```

```http
PUT /api/profile/
Authorization: Bearer <access_token>
Content-Type: application/json

{
    "date_of_birth": "1990-05-15",
    "gender": "male",
    "civil_status": "married",
    "address_line1": "123 Sample Street",
    "barangay": "Poblacion",
    "city_municipality": "Makati",
    "province": "Metro Manila",
    "zip_code": "1234"
}
```

---

### Business Profile

```http
GET /api/profile/business/
Authorization: Bearer <access_token>
```

```http
PUT /api/profile/business/
Authorization: Bearer <access_token>
Content-Type: application/json

{
    "business_name": "Juan's Sari-Sari Store",
    "business_type": "sari_sari_store",
    "years_in_operation": 3.5,
    "is_registered": true,
    "registration_type": "DTI",
    "income_range": "10000_20000",
    "estimated_monthly_income": 15000
}
```

---

### Alternative Data

```http
GET /api/profile/alternative-data/
Authorization: Bearer <access_token>
```

```http
PUT /api/profile/alternative-data/
Authorization: Bearer <access_token>
Content-Type: application/json

{
    "education_level": "high_school",
    "employment_status": "self_employed",
    "housing_status": "owned",
    "years_at_current_address": 5,
    "has_bank_account": true,
    "has_ewallet": true,
    "ewallet_usage": "daily",
    "pays_utilities": true,
    "utility_payment_history": "on_time"
}
```

---

### Profile Summary

Get an overview of all profile completion status:

```http
GET /api/profile/summary/
Authorization: Bearer <access_token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "personal_profile": {
            "completed": true,
            "completion_percentage": 100
        },
        "business_profile": {
            "completed": true,
            "has_business_type": true,
            "has_income_info": true
        },
        "alternative_data": {
            "completed": true,
            "has_risk_score": false,
            "risk_category": null
        },
        "overall": {
            "sections_complete": 3,
            "total_sections": 3,
            "ready_for_loan": true,
            "completion_percentage": 100
        }
    }
}
```

---

## Database Collections

| Collection | Description |
|------------|-------------|
| `customer_profiles` | Personal information |
| `business_profiles` | Business/MSME data |
| `alternative_data` | Alternative credit data |

---

## Related Documentation

- [Authentication](./AUTHENTICATION.md) - Auth flow
- [Roles](./ROLES.md) - User roles
- [Consent](./CONSENT.md) - Data collection consent
