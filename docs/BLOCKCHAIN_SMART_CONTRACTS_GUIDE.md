# Blockchain Smart Contracts Guide

## Scope
This guide covers the on-chain subsystem in `smartcontracts/` and how it maps to backend loan workflows.

## Current Status
| Component | Status |
|---|---|
| Smart contracts | Implemented |
| Local test suite | Implemented (`hardhat test`) |
| Local deployment | Implemented (`deploy:local`) |
| Django/Web3 bridge | Not implemented |

The backend currently does not call contracts directly. A bridge service is still required.

## Contract Inventory
| Contract | Purpose | Core Operations |
|---|---|---|
| `LoanAccessControl.sol` | Officer and borrower identity/role checks | registration and role validation |
| `AuditRegistry.sol` | Immutable activity/event log | append and query audit entries |
| `LoanCore.sol` | Loan lifecycle state machine | create, submit, assign, approve, reject, cancel |
| `Disbursement.sol` | Disbursement execution and tracking | initiate and complete disbursement |
| `Repayment.sol` | Schedules and payment records | create schedule, record payments |

Interfaces used across contracts:
- `ILoanAccessControl.sol`
- `IAuditRegistry.sol`
- `ILoanCore.sol`

## Canonical Enum Mappings
Use contract enums as source of truth to avoid status drift.

### Loan Status (`LoanCore.sol`)
| Value | On-chain Enum | Backend Status |
|---|---|---|
| `0` | `Draft` | `draft` |
| `1` | `Submitted` | `submitted` |
| `2` | `UnderReview` | `under_review` |
| `3` | `Approved` | `approved` |
| `4` | `Rejected` | `rejected` |
| `5` | `Disbursed` | `disbursed` |
| `6` | `Cancelled` | `cancelled` |

Note: `ILoanCore.sol` still contains legacy enum values (`Active`, `Completed`, `Defaulted`) that are not present in `LoanCore.sol`. Align this interface before backend integration.

### Installment Status (`Repayment.sol`)
| Value | On-chain Enum | Backend Status |
|---|---|---|
| `0` | `Pending` | `pending` |
| `1` | `Paid` | `paid` |
| `2` | `Partial` | `partial` |
| `3` | `Overdue` | `overdue` |

### Method Enums (Ordering Matters)
- `Repayment.PaymentMethod`: `Cash(0)`, `BankTransfer(1)`, `GCash(2)`, `Other(3)`
- `Disbursement.DisbursementMethod`: `BankTransfer(0)`, `Cash(1)`, `GCash(2)`, `Other(3)`

## Local Development and Testing
```bash
cd smartcontracts
npm install
npm run compile
npm test
```

Optional local deployment:
```bash
npm run node        # terminal 1
npm run deploy:local  # terminal 2
```

## References
- [smartcontracts/README.md](../smartcontracts/README.md)
- [smartcontracts/docs/TESTING_GUIDE.md](../smartcontracts/docs/TESTING_GUIDE.md)
- [smartcontracts/docs/SMART_CONTRACT_ARCHITECTURE.md](../smartcontracts/docs/SMART_CONTRACT_ARCHITECTURE.md)
