#!/usr/bin/env python3
"""
Extract ABI arrays from Hardhat compilation artifacts into clean JSON files
for the Django blockchain service layer.

Usage:
    python scripts/copy_abis.py
"""

import json
import os
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "smartcontracts" / "artifacts" / "contracts"
OUTPUT_DIR = PROJECT_ROOT / "loans" / "blockchain" / "abis"

# Contract name → artifact path (relative to ARTIFACTS_DIR)
CONTRACTS = {
    "AuditRegistry": "AuditRegistry.sol/AuditRegistry.json",
    "LoanAccessControl": "LoanAccessControl.sol/LoanAccessControl.json",
    "LoanCore": "LoanCore.sol/LoanCore.json",
    "LoanApplication": "core/LoanApplication.sol/LoanApplication.json",
    "LoanReview": "core/LoanReview.sol/LoanReview.json",
    "LoanApproval": "core/LoanApproval.sol/LoanApproval.json",
    "DisbursementMethod": "disbursement/DisbursementMethod.sol/DisbursementMethod.json",
    "DisbursementExecution": "disbursement/DisbursementExecution.sol/DisbursementExecution.json",
    "RepaymentSchedule": "repayment/RepaymentSchedule.sol/RepaymentSchedule.json",
    "PaymentRecording": "repayment/PaymentRecording.sol/PaymentRecording.json",
}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    copied = 0
    for name, rel_path in CONTRACTS.items():
        artifact_path = ARTIFACTS_DIR / rel_path
        if not artifact_path.exists():
            print(f"  ✗ {name}: artifact not found at {artifact_path}")
            continue

        with open(artifact_path, "r") as f:
            artifact = json.load(f)

        abi = artifact.get("abi", [])
        output_path = OUTPUT_DIR / f"{name}.json"

        with open(output_path, "w") as f:
            json.dump(abi, f, indent=2)

        print(f"  ✓ {name}: {len(abi)} ABI entries → {output_path.name}")
        copied += 1

    print(f"\nDone: {copied}/{len(CONTRACTS)} ABIs copied to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
