// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title ILoanApplication
 * @notice Interface for loan application contract - defines cross-contract calls
 * @dev Provides standardized interface for loan application lifecycle management
 */
interface ILoanApplication {
    // ============ Enums ============
    
    /**
     * @notice Loan application status lifecycle
     */
    enum LoanStatus {
        Draft,           // 0 - Created but not submitted
        Submitted,       // 1 - Awaiting review assignment
        UnderReview,     // 2 - Assigned to loan officer
        Approved,        // 3 - Approved, awaiting disbursement
        Rejected,        // 4 - Rejected by loan officer
        Disbursed,       // 5 - Funds transferred to borrower
        Cancelled        // 6 - Cancelled by customer or admin
    }

    /**
     * @notice Risk assessment categories
     */
    enum RiskCategory {
        Low,             // 0 - Low risk borrower
        Medium,          // 1 - Medium risk borrower
        High             // 2 - High risk borrower
    }

    // ============ Structs ============
    
    /**
     * @notice Complete loan application data structure
     * @dev All monetary values in smallest unit (e.g., cents for USD)
     */
    struct Application {
        bytes32 loanId;                  // Unique identifier (hash of off-chain UUID)
        address borrower;                // Borrower's Ethereum wallet address
        bytes32 productId;               // Reference to loan product (hash)
        uint256 requestedAmount;         // Requested loan amount in smallest unit
        uint16 termMonths;               // Loan term duration in months
        uint16 interestRateBps;          // Annual interest rate in basis points (150 = 1.5%)
        LoanStatus status;               // Current application status
        RiskCategory riskCategory;       // AI-assessed risk category
        uint8 eligibilityScore;          // AI eligibility score (0-100)
        bytes32 aiRecommendationHash;    // IPFS/hash of AI analysis report
        uint256 submittedAt;             // Timestamp when submitted for review
        uint256 createdAt;               // Timestamp of application creation
        uint256 updatedAt;               // Timestamp of last update
    }

    /**
     * @notice Alias for Application struct (for cross-contract compatibility)
     * @dev ApplicationData is an alias to maintain API consistency
     */
    struct ApplicationData {
        bytes32 loanId;
        address borrower;
        bytes32 productId;
        uint256 requestedAmount;
        uint16 termMonths;
        uint16 interestRateBps;
        LoanStatus status;
        RiskCategory riskCategory;
        uint8 eligibilityScore;
        bytes32 aiRecommendationHash;
        uint256 submittedAt;
        uint256 createdAt;
        uint256 updatedAt;
    }

    // ============ Events ============
    
    /**
     * @notice Emitted when a new loan application is created
     */
    event ApplicationCreated(
        bytes32 indexed loanId,
        address indexed borrower,
        bytes32 indexed productId,
        uint256 requestedAmount,
        uint16 termMonths,
        uint16 interestRateBps,
        uint256 timestamp
    );

    /**
     * @notice Emitted when application is submitted for review
     */
    event ApplicationSubmitted(
        bytes32 indexed loanId,
        address indexed borrower,
        uint8 eligibilityScore,
        RiskCategory riskCategory,
        bytes32 aiRecommendationHash,
        uint256 timestamp
    );

    /**
     * @notice Emitted when application is cancelled
     */
    event ApplicationCancelled(
        bytes32 indexed loanId,
        address indexed cancelledBy,
        bytes32 reasonHash,
        uint256 timestamp
    );

    /**
     * @notice Emitted when application status changes
     */
    event ApplicationStatusChanged(
        bytes32 indexed loanId,
        LoanStatus oldStatus,
        LoanStatus newStatus,
        uint256 timestamp
    );

    // ============ Core Functions ============
    
    /**
     * @notice Create a new loan application in Draft status
     * @param loanId Unique identifier for the loan
     * @param productId Reference to the loan product
     * @param requestedAmount Amount requested in smallest unit
     * @param termMonths Loan term in months
     * @param interestRateBps Interest rate in basis points
     * @return success True if application created successfully
     */
    function createApplication(
        bytes32 loanId,
        bytes32 productId,
        uint256 requestedAmount,
        uint16 termMonths,
        uint16 interestRateBps
    ) external returns (bool success);

    /**
     * @notice Submit application for review with AI assessment
     * @param loanId The loan application identifier
     * @param eligibilityScore AI-calculated eligibility score (0-100)
     * @param riskCategory AI-assessed risk category
     * @param aiRecommendationHash Hash of AI recommendation report
     * @return success True if submitted successfully
     */
    function submitApplication(
        bytes32 loanId,
        uint8 eligibilityScore,
        RiskCategory riskCategory,
        bytes32 aiRecommendationHash
    ) external returns (bool success);

    /**
     * @notice Cancel an application
     * @param loanId The loan application identifier
     * @param reasonHash Hash of cancellation reason
     * @return success True if cancelled successfully
     */
    function cancelApplication(
        bytes32 loanId,
        bytes32 reasonHash
    ) external returns (bool success);

    /**
     * @notice Update application status (called by authorized contracts)
     * @param loanId The loan application identifier
     * @param newStatus The new status to set
     * @return success True if status updated successfully
     */
    function updateStatus(
        bytes32 loanId,
        LoanStatus newStatus
    ) external returns (bool success);

    /**
     * @notice Update application status without audit logging (caller handles audit)
     * @param loanId The loan application identifier
     * @param newStatus The new status to set
     * @return success True if status updated successfully
     */
    function updateStatusSilent(
        bytes32 loanId,
        LoanStatus newStatus
    ) external returns (bool success);

    // ============ View Functions ============
    
    /**
     * @notice Get complete loan application data
     * @param loanId The loan application identifier
     * @return application Complete Application struct
     */
    function getApplication(bytes32 loanId) external view returns (Application memory application);

    /**
     * @notice Get current loan application status
     * @param loanId The loan application identifier
     * @return status Current LoanStatus
     */
    function getStatus(bytes32 loanId) external view returns (LoanStatus status);

    /**
     * @notice Check if loan application exists
     * @param loanId The loan application identifier
     * @return exists True if application exists
     */
    function exists(bytes32 loanId) external view returns (bool exists);

    /**
     * @notice Get all application IDs for a borrower
     * @param borrower The borrower's wallet address
     * @return loanIds Array of loan application identifiers
     */
    function getBorrowerApplications(address borrower) external view returns (bytes32[] memory loanIds);
}
