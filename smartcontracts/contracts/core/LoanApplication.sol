// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import "../interfaces/ILoanApplication.sol";
import "../interfaces/ILoanAccessControl.sol";
import "../interfaces/IAuditRegistry.sol";

/**
 * @title LoanApplication
 * @notice Handles loan application creation and submission
 * @dev Separated from LoanCore for single responsibility principle
 * @custom:security-contact security@msme-platform.com
 */
contract LoanApplication is 
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable,
    ILoanApplication
{
    // ============ Constants ============
    uint256 public constant VERSION = 1;
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant SYSTEM_ROLE = keccak256("SYSTEM_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ State Variables ============
    ILoanAccessControl public accessControl;
    IAuditRegistry public auditRegistry;

    // Application storage
    mapping(bytes32 => Application) private applications;
    mapping(address => bytes32[]) private borrowerApplications;
    
    // Counters
    uint256 public totalApplications;
    uint256 public totalSubmitted;
    uint256 public totalCancelled;

    // ============ Errors ============
    error ApplicationAlreadyExists(bytes32 loanId);
    error ApplicationNotFound(bytes32 loanId);
    error InvalidStatus(bytes32 loanId, LoanStatus current, LoanStatus expected);
    error UnauthorizedBorrower(bytes32 loanId, address caller);
    error InvalidAmount(uint256 amount);
    error InvalidTerm(uint16 termMonths);
    error InvalidScore(uint8 score);
    error ZeroAddress();
    error EmptyHash();
    error NotBorrower(address caller);

    // ============ Modifiers ============
    
    modifier applicationExists(bytes32 loanId) {
        if (applications[loanId].createdAt == 0) {
            revert ApplicationNotFound(loanId);
        }
        _;
    }

    modifier onlyBorrowerOf(bytes32 loanId) {
        if (applications[loanId].borrower != msg.sender) {
            revert UnauthorizedBorrower(loanId, msg.sender);
        }
        _;
    }

    modifier inStatus(bytes32 loanId, LoanStatus expected) {
        if (applications[loanId].status != expected) {
            revert InvalidStatus(loanId, applications[loanId].status, expected);
        }
        _;
    }

    modifier onlyBorrower() {
        if (!accessControl.isBorrower(msg.sender) && !hasRole(SYSTEM_ROLE, msg.sender)) {
            revert NotBorrower(msg.sender);
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

    // ============ External Functions ============

    /**
     * @notice Create a new loan application
     * @param loanId Unique loan identifier (hash of off-chain ID)
     * @param productId Product identifier
     * @param requestedAmount Amount requested in smallest unit (e.g., wei for ETH)
     * @param termMonths Loan term in months (1-360)
     * @param interestRateBps Interest rate in basis points (e.g., 150 = 1.5%)
     * @return bool Success status
     */
    function createApplication(
        bytes32 loanId,
        bytes32 productId,
        uint256 requestedAmount,
        uint16 termMonths,
        uint16 interestRateBps
    ) external override nonReentrant whenNotPaused onlyBorrower returns (bool) {
        // Validation
        if (applications[loanId].createdAt != 0) {
            revert ApplicationAlreadyExists(loanId);
        }
        if (requestedAmount == 0) {
            revert InvalidAmount(requestedAmount);
        }
        if (termMonths == 0 || termMonths > 360) {
            revert InvalidTerm(termMonths);
        }
        if (productId == bytes32(0)) {
            revert EmptyHash();
        }

        // Create application
        Application storage app = applications[loanId];
        app.loanId = loanId;
        app.borrower = msg.sender;
        app.productId = productId;
        app.requestedAmount = requestedAmount;
        app.termMonths = termMonths;
        app.interestRateBps = interestRateBps;
        app.status = LoanStatus.Draft;
        app.createdAt = block.timestamp;
        app.updatedAt = block.timestamp;

        // Update indexes — borrower applications tracked via ApplicationCreated events
        totalApplications++;

        // Emit event
        emit ApplicationCreated(
            loanId,
            msg.sender,
            productId,
            requestedAmount,
            termMonths,
            interestRateBps,
            block.timestamp
        );

        // Audit log
        auditRegistry.log(
            loanId,
            "application",
            IAuditRegistry.AuditAction.LoanCreated,
            keccak256(abi.encodePacked(msg.sender, productId, requestedAmount)),
            bytes32(0),
            bytes32(uint256(LoanStatus.Draft))
        );

        return true;
    }

    /**
     * @notice Submit application for review
     * @param loanId Loan identifier
     * @param eligibilityScore AI-calculated eligibility score (0-100)
     * @param riskCategory Risk category assessment
     * @param aiRecommendationHash Hash of AI recommendation data
     * @return bool Success status
     */
    function submitApplication(
        bytes32 loanId,
        uint8 eligibilityScore,
        RiskCategory riskCategory,
        bytes32 aiRecommendationHash
    ) external override 
        nonReentrant 
        whenNotPaused 
        applicationExists(loanId)
        onlyBorrowerOf(loanId)
        inStatus(loanId, LoanStatus.Draft)
        returns (bool) 
    {
        // Validation
        if (eligibilityScore > 100) {
            revert InvalidScore(eligibilityScore);
        }
        if (aiRecommendationHash == bytes32(0)) {
            revert EmptyHash();
        }

        Application storage app = applications[loanId];
        LoanStatus oldStatus = app.status;

        // Update application
        app.eligibilityScore = eligibilityScore;
        app.riskCategory = riskCategory;
        app.aiRecommendationHash = aiRecommendationHash;
        app.status = LoanStatus.Submitted;
        app.submittedAt = block.timestamp;
        app.updatedAt = block.timestamp;

        totalSubmitted++;

        // Emit events
        emit ApplicationSubmitted(
            loanId,
            msg.sender,
            eligibilityScore,
            riskCategory,
            aiRecommendationHash,
            block.timestamp
        );

        emit ApplicationStatusChanged(
            loanId,
            oldStatus,
            LoanStatus.Submitted,
            block.timestamp
        );

        // Audit log
        auditRegistry.log(
            loanId,
            "application",
            IAuditRegistry.AuditAction.LoanSubmitted,
            aiRecommendationHash,
            bytes32(uint256(oldStatus)),
            bytes32(uint256(LoanStatus.Submitted))
        );

        return true;
    }

    /**
     * @notice Cancel an application
     * @param loanId Loan identifier
     * @param reasonHash Hash of cancellation reason
     * @return bool Success status
     */
    function cancelApplication(
        bytes32 loanId,
        bytes32 reasonHash
    ) external override 
        nonReentrant 
        whenNotPaused 
        applicationExists(loanId)
        returns (bool) 
    {
        Application storage app = applications[loanId];
        
        // Only borrower or admin can cancel
        if (app.borrower != msg.sender && !hasRole(ADMIN_ROLE, msg.sender)) {
            revert UnauthorizedBorrower(loanId, msg.sender);
        }

        // Can only cancel Draft, Submitted, or Rejected applications
        if (
            app.status != LoanStatus.Draft &&
            app.status != LoanStatus.Submitted &&
            app.status != LoanStatus.Rejected
        ) {
            revert InvalidStatus(loanId, app.status, LoanStatus.Draft);
        }

        if (reasonHash == bytes32(0)) {
            revert EmptyHash();
        }

        LoanStatus oldStatus = app.status;
        app.status = LoanStatus.Cancelled;
        app.updatedAt = block.timestamp;

        totalCancelled++;

        // Emit events
        emit ApplicationCancelled(
            loanId,
            msg.sender,
            reasonHash,
            block.timestamp
        );

        emit ApplicationStatusChanged(
            loanId,
            oldStatus,
            LoanStatus.Cancelled,
            block.timestamp
        );

        // Audit log - using SystemConfigChanged as generic status change action
        auditRegistry.log(
            loanId,
            "application",
            IAuditRegistry.AuditAction.SystemConfigChanged,
            keccak256(abi.encodePacked(msg.sender, reasonHash, "CANCELLED")),
            bytes32(uint256(oldStatus)),
            bytes32(uint256(LoanStatus.Cancelled))
        );

        return true;
    }

    /**
     * @notice Update application status (called by authorized contracts)
     * @param loanId Loan identifier
     * @param newStatus New status to set
     * @return bool Success status
     */
    function updateStatus(
        bytes32 loanId,
        LoanStatus newStatus
    ) external override 
        nonReentrant 
        whenNotPaused
        applicationExists(loanId)
        returns (bool) 
    {
        // Only SYSTEM_ROLE or ADMIN_ROLE can update status
        require(
            hasRole(SYSTEM_ROLE, msg.sender) || hasRole(ADMIN_ROLE, msg.sender),
            "LoanApplication: not authorized to update status"
        );

        Application storage app = applications[loanId];
        LoanStatus oldStatus = app.status;

        // Prevent invalid transitions
        require(oldStatus != newStatus, "LoanApplication: status unchanged");

        app.status = newStatus;
        app.updatedAt = block.timestamp;

        emit ApplicationStatusChanged(
            loanId,
            oldStatus,
            newStatus,
            block.timestamp
        );

        // Audit log - using SystemConfigChanged as generic status change action
        auditRegistry.log(
            loanId,
            "application",
            IAuditRegistry.AuditAction.SystemConfigChanged,
            keccak256(abi.encodePacked(msg.sender, newStatus, "STATUS_UPDATE")),
            bytes32(uint256(oldStatus)),
            bytes32(uint256(newStatus))
        );

        return true;
    }

    /**
     * @notice Update application status without audit logging (caller handles audit)
     * @param loanId Loan identifier
     * @param newStatus New status to set
     * @return bool Success status
     */
    function updateStatusSilent(
        bytes32 loanId,
        LoanStatus newStatus
    ) external override 
        nonReentrant 
        whenNotPaused
        applicationExists(loanId)
        returns (bool) 
    {
        require(
            hasRole(SYSTEM_ROLE, msg.sender) || hasRole(ADMIN_ROLE, msg.sender),
            "LoanApplication: not authorized to update status"
        );

        Application storage app = applications[loanId];
        LoanStatus oldStatus = app.status;
        require(oldStatus != newStatus, "LoanApplication: status unchanged");

        app.status = newStatus;
        app.updatedAt = block.timestamp;

        emit ApplicationStatusChanged(loanId, oldStatus, newStatus, block.timestamp);

        return true;
    }

    // ============ View Functions ============

    /**
     * @notice Get application details
     * @param loanId Loan identifier
     * @return Application struct
     */
    function getApplication(bytes32 loanId) 
        external 
        view 
        override 
        applicationExists(loanId)
        returns (Application memory) 
    {
        return applications[loanId];
    }

    /**
     * @notice Get application status
     * @param loanId Loan identifier
     * @return LoanStatus Current status
     */
    function getStatus(bytes32 loanId) 
        external 
        view 
        override 
        applicationExists(loanId)
        returns (LoanStatus) 
    {
        return applications[loanId].status;
    }

    /**
     * @notice Check if application exists
     * @param loanId Loan identifier
     * @return bool True if exists
     */
    function exists(bytes32 loanId) external view override returns (bool) {
        return applications[loanId].createdAt != 0;
    }

    /**
     * @notice Get all applications for a borrower
     * @dev Deprecated: use ApplicationCreated events for off-chain indexing
     * @param borrower Borrower address
     * @return bytes32[] Array of loan IDs (legacy, may be incomplete)
     */
    function getBorrowerApplications(address borrower) 
        external 
        view 
        override 
        returns (bytes32[] memory) 
    {
        return borrowerApplications[borrower];
    }

    /**
     * @notice Get total number of applications by a borrower
     * @param borrower Borrower address
     * @return uint256 Count of applications
     */
    function getBorrowerApplicationCount(address borrower) 
        external 
        view 
        returns (uint256) 
    {
        return borrowerApplications[borrower].length;
    }

    /**
     * @notice Get system statistics
     * @return _totalApplications Total applications created
     * @return _totalSubmitted Total applications submitted
     * @return _totalCancelled Total applications cancelled
     */
    function getStats() external view returns (
        uint256 _totalApplications,
        uint256 _totalSubmitted,
        uint256 _totalCancelled
    ) {
        return (totalApplications, totalSubmitted, totalCancelled);
    }

    // ============ Admin Functions ============

    /**
     * @notice Pause the contract
     */
    function pause() external onlyRole(ADMIN_ROLE) {
        _pause();
    }

    /**
     * @notice Unpause the contract
     */
    function unpause() external onlyRole(ADMIN_ROLE) {
        _unpause();
    }

    /**
     * @notice Grant SYSTEM_ROLE to a contract
     * @param contractAddress Address to grant role to
     */
    function grantSystemRole(address contractAddress) external onlyRole(ADMIN_ROLE) {
        _grantRole(SYSTEM_ROLE, contractAddress);
    }

    /**
     * @notice Revoke SYSTEM_ROLE from a contract
     * @param contractAddress Address to revoke role from
     */
    function revokeSystemRole(address contractAddress) external onlyRole(ADMIN_ROLE) {
        _revokeRole(SYSTEM_ROLE, contractAddress);
    }

    // ============ Upgrade Functions ============

    /**
     * @notice Authorize upgrade (UUPS pattern)
     * @param newImplementation Address of new implementation
     */
    function _authorizeUpgrade(address newImplementation) 
        internal 
        override 
        onlyRole(UPGRADER_ROLE) 
    {
        // Additional upgrade checks can be added here
    }
}
