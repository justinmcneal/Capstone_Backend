# ERD Gap Analysis

**Assessment: significantly outdated.** The backend uses one MongoDB database through PyMongo; Django ORM is a dummy backend. Mobile/web only validate API data use—Hive, secure storage, and React state are not database entities.

| Current ERD | Actual result |
|---|---|
| `USERS` | Split: `customer`, `loan_officers`, `admins`. |
| `CONSENTS` | `consents` plus `consent_events`; polymorphic `user_id`/`user_type`. |
| `AI_INTERACTIONS` | Exists as `ai_interactions`, with customer/conversation/model/usage fields. |
| `ALTERNATIVE_PROFILES` | Split: personal, business, alternative-data, and risk-review collections. |
| `DOCUMENTS` | Exists; analysis is embedded and file bytes are object/local storage. |
| `LOAN_APPLICATIONS`, `PAYMENTS` | Exist as `loan_applications`, `loan_payments`; add products and schedules. |

| Add / change | Evidence |
|---|---|
| Profiles, loan products/schedules, notifications/device tokens, audit logs | Backend model collections. |
| Sessions, refresh/blacklisted tokens, login activity | Persistent account security data. |
| Document upload/delivery/cleanup, risk reviews, blockchain transactions | Persistent workflow/support records. |
| Money | Payment canonical value is integer `amount_centavos`, not generic float. |
| References | Application-managed ObjectId/string references; MongoDB does not enforce FKs. |
| BPI | Do not add: no client or persisted BPI IDs exist. |

Embedded BSON: document `ai_analysis`; risk breakdown; application notes/transitions; schedule installments; payment allocations; audit details. Runtime S3/FCM/blockchain activation is **UNVERIFIED**.
