# Profiles Implementation and Testing Guide

Merged documentation for profile module implementation and profile API testing.

## Wave

- Wave: 2
- Status: Done

## Navigation

1. [Profile Module Documentation](#section-1-profilemd)
2. [Profile API Testing Guide](#section-2-profiles_testing_guidemd)

## Source Files

1. `PROFILE.md`
2. `PROFILES_TESTING_GUIDE.md`

---

## Section 1: PROFILE.md

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

- [Authentication](./AUTH_ACCESS_SECURITY_GUIDE.md#section-1-authenticationmd) - Auth flow
- [Roles](./AUTH_ACCESS_SECURITY_GUIDE.md#section-5-rolesmd) - User roles
- [Consent](./AUTH_ACCESS_SECURITY_GUIDE.md#section-4-consentmd) - Data collection consent

---

## Section 2: PROFILES_TESTING_GUIDE.md

# Profile API Testing Guide

Complete guide to test all profile endpoints in Insomnia/Postman.

---

## Setup

**Base URL:** `http://localhost:8000/api/profile`

**Headers (all requests require authentication):**
```
Authorization: Bearer <customer_access_token>
Content-Type: application/json
```

> ⚠️ Profile endpoints are for **Customers only**. You must be logged in as a customer.

---

## Personal Profile

### 1. Get Personal Profile

```
GET /api/profile/
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "id": "...",
        "customer_id": "...",
        "date_of_birth": null,
        "gender": null,
        "civil_status": null,
        "nationality": "Filipino",
        "address_line1": "",
        "barangay": "",
        "city_municipality": "",
        "province": "",
        "zip_code": "",
        "emergency_contact_name": "",
        "emergency_contact_phone": "",
        "profile_completed": false,
        "completion_percentage": 0
    }
}
```

---

### 2. Update Personal Profile

```
PUT /api/profile/
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

**Field Options:**
- `gender`: `male`, `female`, `other`, `prefer_not_to_say`
- `civil_status`: `single`, `married`, `widowed`, `separated`

---

## Business Profile

### 3. Get Business Profile

```
GET /api/profile/business/
```

---

### 4. Update Business Profile

```
PUT /api/profile/business/
```

**Body:**
```json
{
    "business_name": "Juan's Sari-Sari Store",
    "business_type": "sari_sari_store",
    "business_description": "Neighborhood convenience store",
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

**Business Type Options:**
| Value | Description |
|-------|-------------|
| `sari_sari_store` | Sari-sari store |
| `market_vendor` | Market vendor/stallholder |
| `home_based_seller` | Home-based seller |
| `food_vendor` | Food vendor/eatery |
| `transport_service` | Tricycle/jeepney operator |
| `freelancer` | Freelance services |
| `agriculture` | Small-scale farming |
| `manufacturing` | Small manufacturing |
| `retail_trade` | Retail trade |
| `other` | Other (specify in business_type_other) |

**Income Range Options:**
| Value | Amount (PHP) |
|-------|--------------|
| `below_10000` | Below ₱10,000 |
| `10000_20000` | ₱10,000 - ₱20,000 |
| `20000_30000` | ₱20,000 - ₱30,000 |
| `30000_50000` | ₱30,000 - ₱50,000 |
| `50000_100000` | ₱50,000 - ₱100,000 |
| `above_100000` | Above ₱100,000 |

**Registration Types:** `DTI`, `SEC`, `BIR`, `none`

---

## Alternative Credit Data

### 5. Get Alternative Data

```
GET /api/profile/alternative-data/
```

---

### 6. Update Alternative Data

```
PUT /api/profile/alternative-data/
```

**Body:**
```json
{
    "education_level": "high_school",
    "employment_status": "self_employed",
    "years_of_experience": 5,
    "housing_status": "owned",
    "years_at_current_address": 5,
    "monthly_rent": 0,
    "number_of_dependents": 2,
    "household_income": 25000,
    "has_existing_loans": false,
    "existing_loan_amount": 0,
    "existing_loan_source": "none",
    "loan_payment_history": "no_history",
    "has_bank_account": true,
    "bank_account_duration": 3,
    "has_ewallet": true,
    "ewallet_usage": "daily",
    "pays_utilities": true,
    "utility_payment_history": "on_time",
    "is_coop_member": false,
    "community_involvement": []
}
```

**Field Options:**

| Field | Options |
|-------|---------|
| `education_level` | `no_formal`, `elementary`, `high_school`, `vocational`, `college_undergraduate`, `college_graduate`, `postgraduate` |
| `employment_status` | `employed`, `self_employed`, `unemployed`, `retired`, `student` |
| `housing_status` | `owned`, `rented`, `living_with_family`, `company_provided` |
| `existing_loan_source` | `bank`, `cooperative`, `microfinance`, `informal`, `family`, `none` |
| `loan_payment_history` | `on_time`, `sometimes_late`, `often_late`, `defaulted`, `no_history` |
| `ewallet_usage` | `daily`, `weekly`, `monthly`, `rarely`, `never` |
| `utility_payment_history` | `on_time`, `sometimes_late`, `often_late` |

---

## Profile Summary

### 7. Get Profile Summary

```
GET /api/profile/summary/
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "customer_id": "...",
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

## Notification Preferences

### 8. Get Notification Preferences

```
GET /api/profile/notifications/
```

**Response:**
```json
{
    "status": "success",
    "message": "Notification preferences retrieved",
    "data": {
        "preferences": {
            "email_loan_updates": true,
            "email_payment_reminders": true,
            "email_promotions": false
        }
    }
}
```

---

### 9. Update Notification Preferences

```
PUT /api/profile/notifications/
```

**Body:**
```json
{
    "preferences": {
        "email_loan_updates": true,
        "email_payment_reminders": true,
        "email_promotions": false
    }
}
```

**Preference Options:**
| Field | Type | Description |
|-------|------|-------------|
| `email_loan_updates` | Boolean | Receive loan application status updates |
| `email_payment_reminders` | Boolean | Receive payment reminders |
| `email_promotions` | Boolean | Receive promotional emails |

**Response:**
```json
{
    "status": "success",
    "message": "Notification preferences updated",
    "data": {
        "preferences": {
            "email_loan_updates": true,
            "email_payment_reminders": true,
            "email_promotions": false
        }
    }
}
```

---

## Testing Flow

1. **Login as customer** → Get access token from `/api/auth/login/`
2. **Check profile summary** → `GET /api/profile/summary/` (all sections empty)
3. **Fill personal profile** → `PUT /api/profile/`
4. **Fill business profile** → `PUT /api/profile/business/`
5. **Fill alternative data** → `PUT /api/profile/alternative-data/`
6. **Check summary again** → `ready_for_loan` should be `true`
7. **Check notification preferences** → `GET /api/profile/notifications/`
8. **Update preferences** → `PUT /api/profile/notifications/`

---

## Error Responses

### 401 Unauthorized
```json
{
    "detail": "Authentication credentials were not provided."
}
```

### 400 Bad Request
```json
{
    "status": "error",
    "message": "Invalid profile data",
    "errors": {
        "gender": ["\"invalid\" is not a valid choice."]
    }
}
```
