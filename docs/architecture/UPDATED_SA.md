# Updated System Architecture

```mermaid
flowchart TB
  subgraph Clients[Client Layer]
    Mobile[MSME Mobile App]
    Officer[Loan Officer Web]
    Admin[System Admin Web]
  end
  subgraph Backend[Modular Django Backend]
    API[Django REST/ASGI API]
    Accounts[Accounts, Identity & Consent]
    Profiles[Profiles & Alternative Data\nRule-based informational risk score]
    Loans[Loan Products, Qualification & Servicing]
    Docs[Document Management]
    AI[AI Assistant]
    Notify[Notifications]
    Analytics[Analytics & Audit Reporting]
    Chain[Conditional Blockchain Adapter]
  end
  subgraph Infra[Infrastructure]
    Redis[Redis: Channels, cache, Celery]
    Celery[Celery Workers & Beat]
  end
  subgraph Data[Data Layer]
    Mongo[(MongoDB: one physical DB\nlogical domain collections)]
    Storage[(Document bytes: local OR\nprivate S3-compatible storage)]
  end
  subgraph External[Conditional External Systems]
    LLM[Groq OR Ollama]
    FCM[Firebase FCM]
    SMTP[SMTP]
    EVM[EVM RPC & Smart Contracts]
    Rate[CoinGecko ETH/PHP]
    Wallet[WalletConnect/Reown Wallet]
  end

  Mobile -->|HTTPS /api| API
  Officer -->|HTTPS /api| API
  Admin -->|HTTPS /api| API
  Mobile -.->|/ws/notifications| Notify
  Officer -.->|/ws/notifications| Notify
  Admin -.->|/ws/notifications| Notify
  API --> Accounts & Profiles & Loans & Docs & AI & Notify & Analytics & Chain
  Accounts & Profiles & Loans & Docs & AI & Notify & Analytics & Chain <--> Mongo
  Docs <--> Storage
  Docs & Loans & Analytics & Chain --> Celery
  Celery <--> Redis
  Notify <--> Redis
  AI <--> LLM
  Loans -.->|optional consent-aware qualification| LLM
  Docs -.->|consented images; optional approved CNN| Celery
  Notify --> FCM & SMTP
  Chain <--> EVM
  Chain --> Rate
  Mobile <--> Wallet
  Wallet --> EVM
```

## Interpretation

- **Client layer:** Flutter serves MSME customers. React contains separate loan-officer and admin experiences with distinct routes/permissions. Kiosk has no source evidence.
- **Backend:** the `/api/` Django URL dispatcher is the real API edge, not a standalone gateway. The labeled domains are modules in one application, not verified microservices.
- **AI:** assistant is Groq/Ollama-backed English/Tagalog chat; risk scoring is deterministic/informational; document classification is conditional on an approved MobileNetV2 artifact.
- **Data:** MongoDB is one physical database with logical collections. Document metadata is MongoDB; document bytes are local development storage or private S3-compatible storage.
- **Infrastructure:** Redis supports Channels, caching and Celery; Celery/beat handles background document, lifecycle, reconciliation and blockchain work.
- **External:** FCM, SMTP, storage, LLM, EVM and CoinGecko have code paths but activation depends on runtime configuration. BPI is excluded: there is no implementation evidence.

## Major corrections

1. Replaced API Gateway with Django REST/ASGI API.
2. Added audit analytics, Redis/Celery, WebSockets, object storage, push/email, and optional blockchain/wallet flows.
3. Renamed Loan Recommendation to Loan Products, Qualification & Servicing.
4. Corrected AI and MongoDB labels; removed unsupported BPI and unverified kiosk.
