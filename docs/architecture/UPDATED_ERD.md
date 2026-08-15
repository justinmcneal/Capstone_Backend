# Updated ERD

`REF` means an application-managed MongoDB reference, not an enforced foreign key. Fields below are the material persisted fields; the model classes are the complete field source.

```mermaid
erDiagram
  CUSTOMER {
    ObjectId _id PK
    string email UK
    string password
    string account_state
  }
  LOAN_OFFICERS {
    ObjectId _id PK
    string employee_id UK
    string email UK
    array permissions
  }
  ADMINS {
    ObjectId _id PK
    string username UK
    string email UK
    array permissions
  }
  CONSENTS {
    ObjectId _id PK
    string user_id REF
    string user_type
    boolean ai_consent
  }
  CUSTOMER_PROFILES {
    ObjectId _id PK
    string customer_id UK_REF
    string mobile_number
    string wallet_address
  }
  BUSINESS_PROFILES {
    ObjectId _id PK
    string customer_id UK_REF
    string business_type
    number estimated_monthly_income
  }
  ALTERNATIVE_DATA {
    ObjectId _id PK
    string customer_id UK_REF
    number risk_score
    object risk_score_breakdown
  }
  LOAN_PRODUCTS {
    ObjectId _id PK
    string code UK
    number min_amount
    number interest_rate
  }
  LOAN_APPLICATIONS {
    ObjectId _id PK
    string customer_id REF
    string product_id REF
    string assigned_officer REF
    string status
  }
  REPAYMENT_SCHEDULES {
    ObjectId _id PK
    string loan_id UK_REF
    int total_amount_centavos
    array installments
  }
  LOAN_PAYMENTS {
    ObjectId _id PK
    string loan_id REF
    string schedule_id REF
    int amount_centavos
    string payment_status
  }
  DOCUMENTS {
    ObjectId _id PK
    string customer_id REF
    string file_path
    object ai_analysis
    string status
  }
  AI_INTERACTIONS {
    ObjectId _id PK
    string customer_id REF
    string conversation_id
    string model_used
    int tokens_used
  }
  NOTIFICATIONS {
    ObjectId _id PK
    string user_id REF
    string user_type
    string status
  }
  AUDIT_LOGS {
    ObjectId _id PK
    string user_id REF
    string action
    string resource_id
  }
  PROFILE_RISK_REVIEWS {
    ObjectId _id PK
    string customer_id REF
    string assigned_officer_id REF
    string status
  }
  BLOCKCHAIN_TRANSACTIONS {
    ObjectId _id PK
    string loan_id REF
    string tx_hash
    string status
  }
  CUSTOMER ||--o| CUSTOMER_PROFILES : has
  CUSTOMER ||--o| BUSINESS_PROFILES : has
  CUSTOMER ||--o| ALTERNATIVE_DATA : has
  CUSTOMER ||--o{ LOAN_APPLICATIONS : submits
  LOAN_PRODUCTS ||--o{ LOAN_APPLICATIONS : selected_for
  LOAN_OFFICERS o|--o{ LOAN_APPLICATIONS : assigned
  LOAN_APPLICATIONS ||--o| REPAYMENT_SCHEDULES : creates
  LOAN_APPLICATIONS ||--o{ LOAN_PAYMENTS : receives
  REPAYMENT_SCHEDULES ||--o{ LOAN_PAYMENTS : allocates
  CUSTOMER ||--o{ DOCUMENTS : uploads
  CUSTOMER ||--o{ AI_INTERACTIONS : creates
  CUSTOMER ||--o{ PROFILE_RISK_REVIEWS : requests
  LOAN_APPLICATIONS ||--o{ BLOCKCHAIN_TRANSACTIONS : records
```

Also persisted but omitted for readability: `consent_events`, `active_sessions`, `login_activity`, `refresh_tokens`, `blacklisted_tokens`, `device_tokens`, document upload/delivery/cleanup records, `ai_activity_events`, `ai_chat_requests`, audit/analytics/loan operational records, and blockchain event/listener/lock records. Polymorphic account records can target customer, officer, or admin.
