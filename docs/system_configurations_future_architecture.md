# System Configurations (Future Architecture)

This document outlines the proposed design and backend requirements for implementing a global "System Configurations" settings page for Super Admins.

## Rationale
Currently, `/admin/settings` exclusively manages the personal profile and security settings of the authenticated admin. However, enterprise systems often require a centralized place to manage platform-wide behavior without requiring code deployments. 

## Proposed Features

### 1. Loan Policies & Limits
Configure the global guardrails for loan origination:
- `MAX_LOAN_AMOUNT`: Maximum allowable loan request (currently hardcoded or product-specific).
- `MIN_ELIGIBILITY_SCORE`: The threshold for automatic rejection vs manual review.
- `AUTO_APPROVAL_THRESHOLD`: Automatically approve applications that exceed a certain score.

### 2. Officer Workload Management
Settings that dictate how loan applications are distributed:
- `MAX_APPLICATIONS_PER_OFFICER`: Prevent officers from being overloaded.
- `AUTO_ASSIGNMENT_ENABLED`: Toggle automatic round-robin assignment on or off.

### 3. Platform Maintenance
Controls for system availability:
- `MAINTENANCE_MODE`: A toggle to disable customer logins and application submissions while allowing admin access.
- `ANNOUNCEMENT_BANNER`: Set a global banner message (e.g., "System maintenance scheduled for midnight").

## Backend Architecture Requirements
To support these features, the backend requires:
1. **New Database Collection**: A single-document collection (e.g., `system_settings`) to persist these values.
2. **Caching Strategy**: Since settings are read frequently (on almost every request or action), they must be heavily cached using Redis/Memcached with proper cache invalidation on updates.
3. **New Endpoints**: 
   - `GET /api/admin/system-settings/` (View settings)
   - `PUT /api/admin/system-settings/` (Update settings)
4. **Permissions Enforcement**: Both endpoints must strictly require the `manage_system` permission.

## Frontend UI Architecture
The UI will reside under `/admin/settings` but within a dedicated "System" or "Platform" tab. It should use form groups to segment configurations logically (e.g., "Loan Engine", "Maintenance", "Features") and provide descriptive helper text for each setting to prevent misconfiguration.
