// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import "./interfaces/ILoanAccessControl.sol";
import "./interfaces/IAuditRegistry.sol";

/**
 * @title LoanCore
 * @notice Core loan lifecycle management contract
 * @dev Handles loan creation, submission, assignment, approval, and rejection
 */
contract LoanCore is 
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable 
{
    // ============ Type Definitions ============
    enum LoanStatus {
        Draft,           // 0 - Created but not submitted
        Submitted,       // 1 - Awaiting review
        UnderReview,     // 2 - Assigned to officer
        Approved,        // 3 - Approved, awaiting disbursement
        Rejected,        // 4 - Rejected by officer
        Disbursed,       // 5 - Funds transferred
        Cancelled        // 6 - Cancelled by customer/admin
    }

    enum RiskCategory {
        Low,
        Medium,
        High
    }

    struct Loan {
        bytes32 loanId;                  // Unique identifier (hash of off-chain ID)
        address borrower;                // Borrower's wallet address
        bytes32 productId;               // Loan product reference
        uint256 requestedAmount;         // Amount requested (in smallest unit)
        uint256 approvedAmount;          // Amount approved
        uint256 disbursedAmount;         // Amount actually disbursed
        uint16 termMonths;               // Loan term in months
        uint16 interestRateBps;          // Interest rate in basis points (150 = 1.5%)
        LoanStatus status;
        RiskCategory riskCategory;
        uint8 eligibilityScore;          // 0-100
        bytes32 aiRecommendationHash;    // Hash of off-chain AI analysis
        address assignedOfficer;
        bytes32 rejectionReasonHash;     // Hash of rejection reason
        bytes32 approvalNotesHash;       // Hash of approval notes
        uint256 submittedAt;
        uint256 approvedAt;
        uint256 rejectedAt;
        uint256 disbursedAt;
        uint256 createdAt;
        uint256 updatedAt;
    }

    // ============ Constants ============
    uint256 public constant VERSION = 1;
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant LOAN_OFFICER_ROLE = keccak256("LOAN_OFFICER_ROLE");
    bytes32 public constant SYSTEM_ROLE = keccak256("SYSTEM_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ State Variables ============
    ILoanAccessControl public accessControl;
    IAuditRegistry public auditRegistry;
    address public disbursementContract;
    address public repaymentContract;
    address public oracleContract;

    // Loan storage
    mapping(bytes32 => Loan) public loans;
    mapping(address => bytes32[]) public borrowerLoans;
    mapping(address => bytes32[]) public officerAssignedLoans;
    
    // Counters
    uint256 public totalLoans;
    uint256 public totalApproved;
    uint256 public totalRejected;
    uint256 public totalDisbursed;

    // ============ Events ============
    event LoanCreated(
        bytes32 indexed loanId,
        address indexed borrower,
        bytes32 indexed productId,
        uint256 requestedAmount,
        uint16 termMonths,
        uint16 interestRateBps,
        uint256 timestamp
    );

    event LoanSubmitted(
        bytes32 indexed loanId,
        address indexed borrower,
        uint8 eligibilityScore,
        RiskCategory riskCategory,
        bytes32 aiRecommendationHash,
        uint256 timestamp
    );

    event LoanAssigned(
        bytes32 indexed loanId,
        address indexed officer,
        address indexed assignedBy,
        uint256 timestamp
    );

    event LoanApproved(
        bytes32 indexed loanId,
        address indexed officer,
        uint256 approvedAmount,
        bytes32 notesHash,
        uint256 timestamp
    );

    event LoanRejected(
        bytes32 indexed loanId,
        address indexed officer,
        bytes32 rejectionReasonHash,
        bytes32 notesHash,
        uint256 timestamp
    );

    event LoanStatusChanged(
        bytes32 indexed loanId,
        LoanStatus oldStatus,
        LoanStatus newStatus,
        uint256 timestamp
    );

    event LoanCancelled(
        bytes32 indexed loanId,
        address indexed cancelledBy,
        bytes32 reasonHash,
        uint256 timestamp
    );

    // ============ Errors ============
    error LoanAlreadyExists(bytes32 loanId);
    error LoanNotFound(bytes32 loanId);
    error InvalidStatus(bytes32 loanId, LoanStatus current, LoanStatus expected);
    error UnauthorizedBorrower(bytes32 loanId, address caller);
    error UnauthorizedOfficer(bytes32 loanId, address caller);
    error InvalidAmount(uint256 amount);
    error ZeroAddress();

    // ============ Modifiers ============
    modifier loanExists(bytes32 loanId) {
        if (loans[loanId].createdAt == 0) revert LoanNotFound(loanId);
        _;
    }

    modifier onlyBorrowerOf(bytes32 loanId) {
        if (
            loans[loanId].borrower != msg.sender &&
            !hasRole(ADMIN_ROLE, msg.sender) &&
            !hasRole(SYSTEM_ROLE, msg.sender)
        ) {
            revert UnauthorizedBorrower(loanId, msg.sender);
        }
        _;
    }

    modifier onlyAssignedOfficer(bytes32 loanId) {
        Loan storage loan = loans[loanId];
        if (loan.assignedOfficer != msg.sender && !hasRole(ADMIN_ROLE, msg.sender)) {
            revert UnauthorizedOfficer(loanId, msg.sender);
        }
        _;
    }

    modifier inStatus(bytes32 loanId, LoanStatus expected) {
        if (loans[loanId].status != expected) {
            revert InvalidStatus(loanId, loans[loanId].status, expected);
        }
        _;
    }

    // ============ Initializer ============
    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /**
     * @notice Initialize the contract
     * @param _accessControl Address of the access control contract
     * @param _auditRegistry Address of the audit registry contract
     * @param admin Address of the initial admin
     */
    function initialize(
        address _accessControl,
        address _auditRegistry,
        address admin
    ) public initializer {
        if (_accessControl == address(0) || _auditRegistry == address(0) || admin == address(0)) {
            revert ZeroAddress();
        }

        __AccessControl_init();
        __ReentrancyGuard_init();
        __Pausable_init();
        __UUPSUpgradeable_init();

        accessControl = ILoanAccessControl(_accessControl);
        auditRegistry = IAuditRegistry(_auditRegistry);

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        _grantRole(UPGRADER_ROLE, admin);
    }

    // ============ Configuration ============

    /**
     * @notice Set related contract addresses
     */
    function setContracts(
        address _disbursement,
        address _repayment,
        address _oracle
    ) external onlyRole(ADMIN_ROLE) {
        if (_disbursement == address(0)) revert ZeroAddress();
        if (_repayment == address(0)) revert ZeroAddress();
        if (_oracle == address(0)) revert ZeroAddress();

        disbursementContract = _disbursement;
        repaymentContract = _repayment;
        oracleContract = _oracle;
    }

    // ============ Loan Lifecycle Functions ============

    /**
     * @notice Create a new loan application
     * @param loanId Unique loan identifier (hash of off-chain ID)
     * @param productId Product identifier
     * @param requestedAmount Amount requested
     * @param termMonths Loan term in months
     * @param interestRateBps Interest rate in basis points
     */
    function createLoan(
        bytes32 loanId,
        bytes32 productId,
        uint256 requestedAmount,
        uint16 termMonths,
        uint16 interestRateBps
    ) external nonReentrant whenNotPaused returns (bool) {
        if (loans[loanId].createdAt != 0) revert LoanAlreadyExists(loanId);
        if (requestedAmount == 0) revert InvalidAmount(requestedAmount);
        require(productId != bytes32(0), "LoanCore: invalid productId");
        
        // Verify borrower is registered
        require(
            accessControl.isBorrower(msg.sender) || hasRole(SYSTEM_ROLE, msg.sender) || hasRole(ADMIN_ROLE, msg.sender),
            "LoanCore: caller not authorized"
        );

        Loan storage loan = loans[loanId];
        loan.loanId = loanId;
        loan.borrower = msg.sender;
        loan.productId = productId;
        loan.requestedAmount = requestedAmount;
        loan.termMonths = termMonths;
        loan.interestRateBps = interestRateBps;
        loan.status = LoanStatus.Draft;
        loan.createdAt = block.timestamp;
        loan.updatedAt = block.timestamp;

        borrowerLoans[msg.sender].push(loanId);
        totalLoans++;

        emit LoanCreated(
            loanId,
            msg.sender,
            productId,
            requestedAmount,
            termMonths,
            interestRateBps,
            block.timestamp
        );

        // Log to audit registry
        auditRegistry.log(
            loanId,
            "loan",
            IAuditRegistry.AuditAction.LoanCreated,
            keccak256(abi.encodePacked(msg.sender, productId, requestedAmount)),
            bytes32(0),
            bytes32(uint256(LoanStatus.Draft))
        );

        return true;
    }

    /**
     * @notice Submit loan for review
     * @param loanId Loan identifier
     * @param eligibilityScore AI-calculated eligibility score (0-100)
     * @param riskCategory Risk category
     * @param aiRecommendationHash Hash of AI recommendation
     */
    function submitLoan(
        bytes32 loanId,
        uint8 eligibilityScore,
        RiskCategory riskCategory,
        bytes32 aiRecommendationHash
    ) external 
        nonReentrant 
        whenNotPaused 
        loanExists(loanId)
        onlyBorrowerOf(loanId)
        inStatus(loanId, LoanStatus.Draft)
        returns (bool) 
    {
        require(eligibilityScore <= 100, "LoanCore: invalid score");

        Loan storage loan = loans[loanId];
        LoanStatus oldStatus = loan.status;

        loan.eligibilityScore = eligibilityScore;
        loan.riskCategory = riskCategory;
        loan.aiRecommendationHash = aiRecommendationHash;
        loan.status = LoanStatus.Submitted;
        loan.submittedAt = block.timestamp;
        loan.updatedAt = block.timestamp;

        emit LoanSubmitted(
            loanId,
            msg.sender,
            eligibilityScore,
            riskCategory,
            aiRecommendationHash,
            block.timestamp
        );

        emit LoanStatusChanged(loanId, oldStatus, LoanStatus.Submitted, block.timestamp);

        auditRegistry.log(
            loanId,
            "loan",
            IAuditRegistry.AuditAction.LoanSubmitted,
            aiRecommendationHash,
            bytes32(uint256(oldStatus)),
            bytes32(uint256(LoanStatus.Submitted))
        );

        return true;
    }

    /**
     * @notice Assign loan to an officer
     * @param loanId Loan identifier
     * @param officer Address of the officer
     */
    function assignOfficer(
        bytes32 loanId,
        address officer
    ) external 
        nonReentrant 
        whenNotPaused 
        loanExists(loanId)
        returns (bool) 
    {
        require(
            hasRole(ADMIN_ROLE, msg.sender) || hasRole(SYSTEM_ROLE, msg.sender),
            "LoanCore: not authorized to assign"
        );
        require(accessControl.isActiveOfficer(officer) || hasRole(ADMIN_ROLE, msg.sender), "LoanCore: invalid officer");

        Loan storage loan = loans[loanId];
        require(
            loan.status == LoanStatus.Submitted || loan.status == LoanStatus.UnderReview,
            "LoanCore: invalid status for assignment"
        );

        LoanStatus oldStatus = loan.status;
        loan.assignedOfficer = officer;
        loan.status = LoanStatus.UnderReview;
        loan.updatedAt = block.timestamp;

        officerAssignedLoans[officer].push(loanId);

        emit LoanAssigned(loanId, officer, msg.sender, block.timestamp);

        if (oldStatus != LoanStatus.UnderReview) {
            emit LoanStatusChanged(loanId, oldStatus, LoanStatus.UnderReview, block.timestamp);
        }

        auditRegistry.log(
            loanId,
            "loan",
            IAuditRegistry.AuditAction.LoanAssigned,
            keccak256(abi.encodePacked(officer, msg.sender)),
            bytes32(uint256(oldStatus)),
            bytes32(uint256(LoanStatus.UnderReview))
        );

        return true;
    }

    /**
     * @notice Approve a loan
     * @param loanId Loan identifier
     * @param approvedAmount Amount approved
     * @param notesHash Hash of approval notes
     */
    function approveLoan(
        bytes32 loanId,
        uint256 approvedAmount,
        bytes32 notesHash
    ) external 
        nonReentrant 
        whenNotPaused 
        loanExists(loanId)
        onlyAssignedOfficer(loanId)
        inStatus(loanId, LoanStatus.UnderReview)
        returns (bool) 
    {
        Loan storage loan = loans[loanId];
        
        require(approvedAmount > 0, "LoanCore: amount must be positive");
        require(approvedAmount <= loan.requestedAmount, "LoanCore: exceeds requested");

        LoanStatus oldStatus = loan.status;
        loan.approvedAmount = approvedAmount;
        loan.approvalNotesHash = notesHash;
        loan.status = LoanStatus.Approved;
        loan.approvedAt = block.timestamp;
        loan.updatedAt = block.timestamp;

        totalApproved++;

        emit LoanApproved(loanId, msg.sender, approvedAmount, notesHash, block.timestamp);
        emit LoanStatusChanged(loanId, oldStatus, LoanStatus.Approved, block.timestamp);

        auditRegistry.log(
            loanId,
            "loan",
            IAuditRegistry.AuditAction.LoanApproved,
            keccak256(abi.encodePacked(msg.sender, approvedAmount, notesHash)),
            bytes32(uint256(oldStatus)),
            bytes32(uint256(LoanStatus.Approved))
        );

        return true;
    }

    /**
     * @notice Reject a loan
     * @param loanId Loan identifier
     * @param rejectionReasonHash Hash of rejection reason
     * @param notesHash Hash of notes
     */
    function rejectLoan(
        bytes32 loanId,
        bytes32 rejectionReasonHash,
        bytes32 notesHash
    ) external 
        nonReentrant 
        whenNotPaused 
        loanExists(loanId)
        onlyAssignedOfficer(loanId)
        inStatus(loanId, LoanStatus.UnderReview)
        returns (bool) 
    {
        require(rejectionReasonHash != bytes32(0), "LoanCore: reason required");

        Loan storage loan = loans[loanId];
        LoanStatus oldStatus = loan.status;

        loan.rejectionReasonHash = rejectionReasonHash;
        loan.approvalNotesHash = notesHash;
        loan.status = LoanStatus.Rejected;
        loan.rejectedAt = block.timestamp;
        loan.updatedAt = block.timestamp;

        totalRejected++;

        emit LoanRejected(loanId, msg.sender, rejectionReasonHash, notesHash, block.timestamp);
        emit LoanStatusChanged(loanId, oldStatus, LoanStatus.Rejected, block.timestamp);

        auditRegistry.log(
            loanId,
            "loan",
            IAuditRegistry.AuditAction.LoanRejected,
            keccak256(abi.encodePacked(msg.sender, rejectionReasonHash)),
            bytes32(uint256(oldStatus)),
            bytes32(uint256(LoanStatus.Rejected))
        );

        return true;
    }

    /**
     * @notice Mark loan as disbursed (called by Disbursement contract)
     * @param loanId Loan identifier
     * @param amount Disbursed amount
     */
    function markDisbursed(
        bytes32 loanId,
        uint256 amount
    ) external 
        nonReentrant
        whenNotPaused
        loanExists(loanId) 
        inStatus(loanId, LoanStatus.Approved)
        returns (bool) 
    {
        require(
            msg.sender == disbursementContract || hasRole(ADMIN_ROLE, msg.sender),
            "LoanCore: not authorized"
        );

        Loan storage loan = loans[loanId];
        require(amount <= loan.approvedAmount, "LoanCore: exceeds approved");

        LoanStatus oldStatus = loan.status;
        loan.disbursedAmount = amount;
        loan.status = LoanStatus.Disbursed;
        loan.disbursedAt = block.timestamp;
        loan.updatedAt = block.timestamp;

        totalDisbursed++;

        emit LoanStatusChanged(loanId, oldStatus, LoanStatus.Disbursed, block.timestamp);

        return true;
    }

    /**
     * @notice Cancel a loan (only in draft/submitted status)
     */
    function cancelLoan(
        bytes32 loanId,
        bytes32 reasonHash
    ) external 
        nonReentrant 
        whenNotPaused
        loanExists(loanId) 
        returns (bool) 
    {
        Loan storage loan = loans[loanId];
        
        require(
            loan.borrower == msg.sender || hasRole(ADMIN_ROLE, msg.sender),
            "LoanCore: not authorized"
        );
        require(
            loan.status == LoanStatus.Draft || loan.status == LoanStatus.Submitted,
            "LoanCore: cannot cancel at this stage"
        );

        LoanStatus oldStatus = loan.status;
        loan.status = LoanStatus.Cancelled;
        loan.updatedAt = block.timestamp;

        emit LoanCancelled(loanId, msg.sender, reasonHash, block.timestamp);
        emit LoanStatusChanged(loanId, oldStatus, LoanStatus.Cancelled, block.timestamp);

        return true;
    }

    // ============ View Functions ============

    /**
     * @notice Get loan details
     */
    function getLoan(bytes32 loanId) external view returns (Loan memory) {
        return loans[loanId];
    }

    /**
     * @notice Get loan status
     */
    function getLoanStatus(bytes32 loanId) external view returns (LoanStatus) {
        return loans[loanId].status;
    }

    /**
     * @notice Get all loans for a borrower
     */
    function getBorrowerLoans(address borrower) external view returns (bytes32[] memory) {
        return borrowerLoans[borrower];
    }

    /**
     * @notice Get all loans assigned to an officer
     */
    function getOfficerLoans(address officer) external view returns (bytes32[] memory) {
        return officerAssignedLoans[officer];
    }

    /**
     * @notice Get system statistics
     */
    function getStats() external view returns (
        uint256 _totalLoans,
        uint256 _totalApproved,
        uint256 _totalRejected,
        uint256 _totalDisbursed
    ) {
        return (totalLoans, totalApproved, totalRejected, totalDisbursed);
    }

    // ============ Emergency Functions ============

    function pause() external onlyRole(ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(ADMIN_ROLE) {
        _unpause();
    }

    // ============ Upgrade Functions ============

    function _authorizeUpgrade(address newImplementation) internal override onlyRole(UPGRADER_ROLE) {}
}
