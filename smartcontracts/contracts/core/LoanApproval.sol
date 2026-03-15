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
 * @title LoanApproval
 * @notice Handles loan approval and rejection decisions
 * @dev Separated from LoanCore for single responsibility principle
 * @custom:security-contact security@msme-platform.com
 */
contract LoanApproval is
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable
{
    // ============ Constants ============
    uint256 public constant VERSION = 1;
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant SYSTEM_ROLE = keccak256("SYSTEM_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ State Variables ============
    ILoanAccessControl public accessControl;
    IAuditRegistry public auditRegistry;
    ILoanApplication public loanApplication;

    // Reference to LoanReview for officer assignment lookups
    address public loanReviewContract;

    // Approval/rejection data
    mapping(bytes32 => uint256) public approvedAmounts;
    mapping(bytes32 => bytes32) public approvalNotesHashes;
    mapping(bytes32 => bytes32) public rejectionReasonHashes;
    mapping(bytes32 => bytes32) public rejectionNotesHashes;
    mapping(bytes32 => address) public decisionMakers;
    mapping(bytes32 => uint256) public decisionTimestamps;

    // Counters
    uint256 public totalApproved;
    uint256 public totalRejected;

    // ============ Events ============
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
        bytes32 reasonHash,
        uint256 timestamp
    );

    // ============ Errors ============
    error ZeroAddress();
    error ApplicationNotFound(bytes32 loanId);
    error InvalidApplicationStatus(bytes32 loanId);
    error NotAuthorized(address caller);
    error InvalidAmount(uint256 amount);
    error AmountExceedsRequested(uint256 approved, uint256 requested);
    error EmptyHash();

    // ============ Initializer ============

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /**
     * @notice Initialize the contract
     * @param _accessControl Address of the access control contract
     * @param _auditRegistry Address of the audit registry contract
     * @param _loanApplication Address of the loan application contract
     * @param _loanReview Address of the loan review contract
     * @param admin Address of the initial admin
     */
    function initialize(
        address _accessControl,
        address _auditRegistry,
        address _loanApplication,
        address _loanReview,
        address admin
    ) public initializer {
        if (
            _accessControl == address(0) ||
            _auditRegistry == address(0) ||
            _loanApplication == address(0) ||
            _loanReview == address(0) ||
            admin == address(0)
        ) {
            revert ZeroAddress();
        }

        __AccessControl_init();
        __ReentrancyGuard_init();
        __Pausable_init();
        __UUPSUpgradeable_init();

        accessControl = ILoanAccessControl(_accessControl);
        auditRegistry = IAuditRegistry(_auditRegistry);
        loanApplication = ILoanApplication(_loanApplication);
        loanReviewContract = _loanReview;

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        _grantRole(UPGRADER_ROLE, admin);
    }

    // ============ External Functions ============

    /**
     * @notice Approve a loan application
     * @param loanId Loan identifier
     * @param approvedAmount Amount approved (must not exceed requested amount)
     * @param notesHash Hash of approval notes
     * @return bool Success status
     */
    function approveLoan(
        bytes32 loanId,
        uint256 approvedAmount,
        bytes32 notesHash
    ) external nonReentrant whenNotPaused returns (bool) {
        // Validate application exists
        if (!loanApplication.exists(loanId)) {
            revert ApplicationNotFound(loanId);
        }

        // Validate caller is assigned officer or admin
        _validateCallerIsOfficerOrAdmin(loanId);

        // Validate application is in UnderReview status
        ILoanApplication.LoanStatus status = loanApplication.getStatus(loanId);
        if (status != ILoanApplication.LoanStatus.UnderReview) {
            revert InvalidApplicationStatus(loanId);
        }

        // Validate approved amount
        if (approvedAmount == 0) {
            revert InvalidAmount(approvedAmount);
        }

        ILoanApplication.Application memory app = loanApplication.getApplication(loanId);
        if (approvedAmount > app.requestedAmount) {
            revert AmountExceedsRequested(approvedAmount, app.requestedAmount);
        }

        // Store approval data
        approvedAmounts[loanId] = approvedAmount;
        approvalNotesHashes[loanId] = notesHash;
        decisionMakers[loanId] = msg.sender;
        decisionTimestamps[loanId] = block.timestamp;
        totalApproved++;

        // Update application status to Approved (silent — we log below)
        loanApplication.updateStatusSilent(loanId, ILoanApplication.LoanStatus.Approved);

        emit LoanApproved(loanId, msg.sender, approvedAmount, notesHash, block.timestamp);

        // Audit log
        auditRegistry.log(
            loanId,
            "approval",
            IAuditRegistry.AuditAction.LoanApproved,
            keccak256(abi.encodePacked(msg.sender, approvedAmount, notesHash)),
            bytes32(uint256(status)),
            bytes32(uint256(ILoanApplication.LoanStatus.Approved))
        );

        return true;
    }

    /**
     * @notice Reject a loan application
     * @param loanId Loan identifier
     * @param rejectionReasonHash Hash of the rejection reason (cannot be empty)
     * @param notesHash Hash of additional notes
     * @return bool Success status
     */
    function rejectLoan(
        bytes32 loanId,
        bytes32 rejectionReasonHash,
        bytes32 notesHash
    ) external nonReentrant whenNotPaused returns (bool) {
        // Validate application exists
        if (!loanApplication.exists(loanId)) {
            revert ApplicationNotFound(loanId);
        }

        // Validate caller is assigned officer or admin
        _validateCallerIsOfficerOrAdmin(loanId);

        // Validate application is in UnderReview status
        ILoanApplication.LoanStatus status = loanApplication.getStatus(loanId);
        if (status != ILoanApplication.LoanStatus.UnderReview) {
            revert InvalidApplicationStatus(loanId);
        }

        // Validate rejection reason hash is not empty
        if (rejectionReasonHash == bytes32(0)) {
            revert EmptyHash();
        }

        // Store rejection data
        rejectionReasonHashes[loanId] = rejectionReasonHash;
        rejectionNotesHashes[loanId] = notesHash;
        decisionMakers[loanId] = msg.sender;
        decisionTimestamps[loanId] = block.timestamp;
        totalRejected++;

        // Update application status to Rejected (silent — we log below)
        loanApplication.updateStatusSilent(loanId, ILoanApplication.LoanStatus.Rejected);

        emit LoanRejected(loanId, msg.sender, rejectionReasonHash, block.timestamp);

        // Audit log
        auditRegistry.log(
            loanId,
            "approval",
            IAuditRegistry.AuditAction.LoanRejected,
            keccak256(abi.encodePacked(msg.sender, rejectionReasonHash)),
            bytes32(uint256(status)),
            bytes32(uint256(ILoanApplication.LoanStatus.Rejected))
        );

        return true;
    }

    // ============ Internal Functions ============

    /**
     * @notice Validate that caller is the assigned officer or admin
     * @param loanId Loan identifier
     */
    function _validateCallerIsOfficerOrAdmin(bytes32 loanId) internal view {
        if (hasRole(ADMIN_ROLE, msg.sender)) {
            return;
        }

        // Check if caller is the assigned officer via LoanReview
        // Use low-level staticcall to read assignedOfficers(loanId)
        (bool success, bytes memory data) = loanReviewContract.staticcall(
            abi.encodeWithSignature("getAssignedOfficer(bytes32)", loanId)
        );

        if (!success || data.length == 0) {
            revert NotAuthorized(msg.sender);
        }

        address assignedOfficer = abi.decode(data, (address));
        if (assignedOfficer != msg.sender) {
            revert NotAuthorized(msg.sender);
        }
    }

    // ============ View Functions ============

    /**
     * @notice Get approval details for a loan
     * @param loanId Loan identifier
     * @return amount Approved amount
     * @return notesHash Approval notes hash
     * @return officer Decision maker address
     * @return timestamp Decision timestamp
     */
    function getApprovalDetails(bytes32 loanId) external view returns (
        uint256 amount,
        bytes32 notesHash,
        address officer,
        uint256 timestamp
    ) {
        return (
            approvedAmounts[loanId],
            approvalNotesHashes[loanId],
            decisionMakers[loanId],
            decisionTimestamps[loanId]
        );
    }

    /**
     * @notice Get rejection details for a loan
     * @param loanId Loan identifier
     * @return reasonHash Rejection reason hash
     * @return notesHash Rejection notes hash
     * @return officer Decision maker address
     * @return timestamp Decision timestamp
     */
    function getRejectionDetails(bytes32 loanId) external view returns (
        bytes32 reasonHash,
        bytes32 notesHash,
        address officer,
        uint256 timestamp
    ) {
        return (
            rejectionReasonHashes[loanId],
            rejectionNotesHashes[loanId],
            decisionMakers[loanId],
            decisionTimestamps[loanId]
        );
    }

    /**
     * @notice Get system statistics
     * @return _totalApproved Total approved loans
     * @return _totalRejected Total rejected loans
     */
    function getStats() external view returns (
        uint256 _totalApproved,
        uint256 _totalRejected
    ) {
        return (totalApproved, totalRejected);
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
     * @notice Update the loan review contract address
     * @param _loanReview New loan review contract address
     */
    function setLoanReviewContract(address _loanReview) external onlyRole(ADMIN_ROLE) {
        if (_loanReview == address(0)) {
            revert ZeroAddress();
        }
        loanReviewContract = _loanReview;
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
