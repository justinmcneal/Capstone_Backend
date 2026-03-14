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
 * @title LoanReview
 * @notice Handles officer assignment and review workflow for loan applications
 * @dev Separated from LoanCore for single responsibility principle
 * @custom:security-contact security@msme-platform.com
 */
contract LoanReview is
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

    // Officer assignment tracking
    mapping(bytes32 => address) public assignedOfficers;
    mapping(address => bytes32[]) private officerAssignedLoans;

    // Document request tracking
    mapping(bytes32 => bytes32[]) private requestedDocuments;

    // Counters
    uint256 public totalAssignments;
    uint256 public totalReassignments;
    uint256 public totalDocumentRequests;

    // ============ Events ============
    event OfficerAssigned(
        bytes32 indexed loanId,
        address indexed officer,
        address indexed assignedBy,
        uint256 timestamp
    );

    event OfficerReassigned(
        bytes32 indexed loanId,
        address indexed oldOfficer,
        address indexed newOfficer,
        uint256 timestamp
    );

    event DocumentsRequested(
        bytes32 indexed loanId,
        bytes32[] documentTypes,
        address indexed requestedBy,
        uint256 timestamp
    );

    // ============ Errors ============
    error ZeroAddress();
    error ApplicationNotFound(bytes32 loanId);
    error InvalidApplicationStatus(bytes32 loanId);
    error OfficerNotActive(address officer);
    error NotAuthorized(address caller);
    error OfficerAlreadyAssigned(bytes32 loanId, address officer);
    error NoOfficerAssigned(bytes32 loanId);
    error SameOfficer(bytes32 loanId, address officer);
    error EmptyDocumentTypes();
    error EmptyHash();

    // ============ Modifiers ============

    modifier onlyAdminOrSystem() {
        if (!hasRole(ADMIN_ROLE, msg.sender) && !hasRole(SYSTEM_ROLE, msg.sender)) {
            revert NotAuthorized(msg.sender);
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
     * @param _loanApplication Address of the loan application contract
     * @param admin Address of the initial admin
     */
    function initialize(
        address _accessControl,
        address _auditRegistry,
        address _loanApplication,
        address admin
    ) public initializer {
        if (
            _accessControl == address(0) ||
            _auditRegistry == address(0) ||
            _loanApplication == address(0) ||
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

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        _grantRole(UPGRADER_ROLE, admin);
    }

    // ============ External Functions ============

    /**
     * @notice Assign an officer to a loan application
     * @param loanId Loan identifier
     * @param officer Address of the officer to assign
     * @return bool Success status
     */
    function assignOfficer(
        bytes32 loanId,
        address officer
    ) external nonReentrant whenNotPaused onlyAdminOrSystem returns (bool) {
        // Validate application exists
        if (!loanApplication.exists(loanId)) {
            revert ApplicationNotFound(loanId);
        }

        // Validate application status (must be Submitted or UnderReview)
        ILoanApplication.LoanStatus status = loanApplication.getStatus(loanId);
        if (
            status != ILoanApplication.LoanStatus.Submitted &&
            status != ILoanApplication.LoanStatus.UnderReview
        ) {
            revert InvalidApplicationStatus(loanId);
        }

        // Validate officer is active
        if (!accessControl.isActiveOfficer(officer)) {
            revert OfficerNotActive(officer);
        }

        // Store assignment — officer loan list tracked via OfficerAssigned events
        assignedOfficers[loanId] = officer;
        totalAssignments++;

        // Update application status to UnderReview (silent — we log below)
        if (status == ILoanApplication.LoanStatus.Submitted) {
            loanApplication.updateStatusSilent(loanId, ILoanApplication.LoanStatus.UnderReview);
        }

        emit OfficerAssigned(loanId, officer, msg.sender, block.timestamp);

        // Audit log
        auditRegistry.log(
            loanId,
            "review",
            IAuditRegistry.AuditAction.LoanAssigned,
            keccak256(abi.encodePacked(officer, msg.sender)),
            bytes32(uint256(status)),
            bytes32(uint256(ILoanApplication.LoanStatus.UnderReview))
        );

        return true;
    }

    /**
     * @notice Reassign a loan to a different officer
     * @param loanId Loan identifier
     * @param newOfficer Address of the new officer
     * @param reasonHash Hash of the reassignment reason
     * @return bool Success status
     */
    function reassignOfficer(
        bytes32 loanId,
        address newOfficer,
        bytes32 reasonHash
    ) external nonReentrant whenNotPaused onlyAdminOrSystem returns (bool) {
        // Validate application exists
        if (!loanApplication.exists(loanId)) {
            revert ApplicationNotFound(loanId);
        }

        // Must have an existing assignment
        address oldOfficer = assignedOfficers[loanId];
        if (oldOfficer == address(0)) {
            revert NoOfficerAssigned(loanId);
        }

        // Cannot reassign to the same officer
        if (oldOfficer == newOfficer) {
            revert SameOfficer(loanId, newOfficer);
        }

        // Validate new officer is active
        if (!accessControl.isActiveOfficer(newOfficer)) {
            revert OfficerNotActive(newOfficer);
        }

        // Validate reason hash is not empty
        if (reasonHash == bytes32(0)) {
            revert EmptyHash();
        }

        // Validate application status (must be UnderReview)
        ILoanApplication.LoanStatus status = loanApplication.getStatus(loanId);
        if (status != ILoanApplication.LoanStatus.UnderReview) {
            revert InvalidApplicationStatus(loanId);
        }

        // Update assignment — officer loan list tracked via events
        assignedOfficers[loanId] = newOfficer;
        totalReassignments++;

        emit OfficerReassigned(loanId, oldOfficer, newOfficer, block.timestamp);

        // Audit log
        auditRegistry.log(
            loanId,
            "review",
            IAuditRegistry.AuditAction.LoanAssigned,
            keccak256(abi.encodePacked(oldOfficer, newOfficer, reasonHash)),
            bytes32(uint256(status)),
            bytes32(uint256(ILoanApplication.LoanStatus.UnderReview))
        );

        return true;
    }

    /**
     * @notice Request additional documents from borrower
     * @param loanId Loan identifier
     * @param documentTypeHashes Array of document type hashes being requested
     * @param reasonHash Hash of the reason for requesting documents
     * @return bool Success status
     */
    function requestDocuments(
        bytes32 loanId,
        bytes32[] calldata documentTypeHashes,
        bytes32 reasonHash
    ) external nonReentrant whenNotPaused returns (bool) {
        // Validate application exists
        if (!loanApplication.exists(loanId)) {
            revert ApplicationNotFound(loanId);
        }

        // Only assigned officer or admin can request documents
        address currentOfficer = assignedOfficers[loanId];
        if (
            msg.sender != currentOfficer &&
            !hasRole(ADMIN_ROLE, msg.sender)
        ) {
            revert NotAuthorized(msg.sender);
        }

        // Validate application status (must be UnderReview)
        ILoanApplication.LoanStatus status = loanApplication.getStatus(loanId);
        if (status != ILoanApplication.LoanStatus.UnderReview) {
            revert InvalidApplicationStatus(loanId);
        }

        // Validate document types not empty
        if (documentTypeHashes.length == 0) {
            revert EmptyDocumentTypes();
        }

        // Validate reason hash
        if (reasonHash == bytes32(0)) {
            revert EmptyHash();
        }

        // Documents tracked via DocumentsRequested events for gas efficiency
        totalDocumentRequests++;

        emit DocumentsRequested(loanId, documentTypeHashes, msg.sender, block.timestamp);

        // Audit log
        auditRegistry.log(
            loanId,
            "review",
            IAuditRegistry.AuditAction.DocumentVerified,
            keccak256(abi.encodePacked(msg.sender, reasonHash, documentTypeHashes.length)),
            bytes32(uint256(status)),
            bytes32(uint256(ILoanApplication.LoanStatus.UnderReview))
        );

        return true;
    }

    // ============ View Functions ============

    /**
     * @notice Get the assigned officer for a loan
     * @param loanId Loan identifier
     * @return address Officer address
     */
    function getAssignedOfficer(bytes32 loanId) external view returns (address) {
        return assignedOfficers[loanId];
    }

    /**
     * @notice Get all loans assigned to an officer
     * @param officer Officer address
     * @return bytes32[] Array of loan IDs
     */
    function getOfficerLoans(address officer) external view returns (bytes32[] memory) {
        return officerAssignedLoans[officer];
    }

    /**
     * @notice Get requested documents for a loan
     * @param loanId Loan identifier
     * @return bytes32[] Array of document type hashes
     */
    function getRequestedDocuments(bytes32 loanId) external view returns (bytes32[] memory) {
        return requestedDocuments[loanId];
    }

    /**
     * @notice Get system statistics
     * @return _totalAssignments Total officer assignments
     * @return _totalReassignments Total officer reassignments
     * @return _totalDocumentRequests Total document requests
     */
    function getStats() external view returns (
        uint256 _totalAssignments,
        uint256 _totalReassignments,
        uint256 _totalDocumentRequests
    ) {
        return (totalAssignments, totalReassignments, totalDocumentRequests);
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
