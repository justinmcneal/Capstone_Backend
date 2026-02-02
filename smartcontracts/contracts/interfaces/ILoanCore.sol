// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title ILoanCore
 * @notice Interface for the core loan management contract
 */
interface ILoanCore {
    enum LoanStatus {
        Draft,
        Submitted,
        UnderReview,
        Approved,
        Rejected,
        Disbursed,
        Active,
        Completed,
        Defaulted,
        Cancelled
    }

    enum RiskCategory {
        Low,
        Medium,
        High
    }

    struct Loan {
        bytes32 loanId;
        address borrower;
        bytes32 productId;
        uint256 requestedAmount;
        uint256 approvedAmount;
        uint256 disbursedAmount;
        uint16 termMonths;
        uint16 interestRateBps;
        LoanStatus status;
        RiskCategory riskCategory;
        uint8 eligibilityScore;
        bytes32 aiRecommendationHash;
        address assignedOfficer;
        bytes32 rejectionReasonHash;
        bytes32 approvalNotesHash;
        uint256 submittedAt;
        uint256 approvedAt;
        uint256 rejectedAt;
        uint256 disbursedAt;
        uint256 createdAt;
        uint256 updatedAt;
    }

    function getLoan(bytes32 loanId) external view returns (Loan memory);
    function getLoanStatus(bytes32 loanId) external view returns (LoanStatus);
    function markDisbursed(bytes32 loanId, uint256 amount) external returns (bool);
    function markActive(bytes32 loanId) external returns (bool);
    function markCompleted(bytes32 loanId) external returns (bool);
    function markDefaulted(bytes32 loanId) external returns (bool);
    function revertToApproved(bytes32 loanId) external returns (bool);
}
