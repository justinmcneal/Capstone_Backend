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
import "./DisbursementMethod.sol";

/**
 * @title DisbursementExecution
 * @notice Handles actual loan disbursement execution
 * @dev Refactored from Disbursement.sol - reads method from DisbursementMethod contract
 * @custom:security-contact security@msme-platform.com
 */
contract DisbursementExecution is 
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable 
{
    // ============ Enums ============
    
    /**
     * @notice Disbursement execution status
     */
    enum Status {
        Pending,         // 0 - Awaiting disbursement
        Processing,      // 1 - In progress
        Completed,       // 2 - Successfully disbursed
        Cancelled        // 3 - Cancelled/failed
    }

    // ============ Structs ============
    
    /**
     * @notice Complete disbursement execution record
     */
    struct DisbursementRecord {
        bytes32 disbursementId;
        bytes32 loanId;
        address borrower;
        uint256 amount;
        DisbursementMethod.Method method;
        bytes32 referenceHash;           // Hash of external reference number
        Status status;
        address processedBy;             // Officer who processed
        uint256 initiatedAt;
        uint256 processedAt;
        bytes32 cancellationReason;      // Hash of cancellation reason (if cancelled)
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
    ILoanApplication public loanApplication;
    DisbursementMethod public disbursementMethod;

    // Disbursement storage
    mapping(bytes32 => DisbursementRecord) private disbursements;
    mapping(bytes32 => bytes32) private loanToDisbursement;  // loanId => disbursementId
    mapping(bytes32 => bool) private usedReferences;         // Prevent duplicate references
    
    // Counters
    uint256 public totalDisbursements;
    uint256 public totalCompleted;
    uint256 public totalCancelled;
    uint256 public totalDisbursedAmount;
    uint256 private _disbursementNonce;

    // ============ Events ============
    
    event DisbursementInitiated(
        bytes32 indexed disbursementId,
        bytes32 indexed loanId,
        address indexed borrower,
        uint256 amount,
        DisbursementMethod.Method method,
        address initiatedBy,
        uint256 timestamp
    );

    event DisbursementCompleted(
        bytes32 indexed disbursementId,
        bytes32 indexed loanId,
        bytes32 referenceHash,
        address processedBy,
        uint256 timestamp
    );

    event DisbursementCancelled(
        bytes32 indexed disbursementId,
        bytes32 indexed loanId,
        bytes32 reasonHash,
        address cancelledBy,
        uint256 timestamp
    );

    // ============ Errors ============
    
    error ZeroAddress();
    error DisbursementNotFound(bytes32 disbursementId);
    error InvalidStatus(bytes32 disbursementId, Status current, Status expected);
    error DuplicateReference(bytes32 referenceHash);
    error LoanNotApproved(bytes32 loanId, ILoanApplication.LoanStatus current);
    error AlreadyDisbursed(bytes32 loanId);
    error InvalidAmount(uint256 amount, uint256 approvedAmount);
    error NoPreferredMethod(bytes32 loanId);
    error EmptyHash();
    error NotAuthorized(address caller);

    // ============ Modifiers ============
    
    modifier disbursementExists(bytes32 disbursementId) {
        if (disbursements[disbursementId].initiatedAt == 0) {
            revert DisbursementNotFound(disbursementId);
        }
        _;
    }

    modifier onlyAuthorized() {
        if (!hasRole(LOAN_OFFICER_ROLE, msg.sender) && 
            !hasRole(ADMIN_ROLE, msg.sender) && 
            !hasRole(SYSTEM_ROLE, msg.sender)) {
            revert NotAuthorized(msg.sender);
        }
        _;
    }

    // ============ Initialization ============
    
    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /**
     * @notice Initialize the contract
     * @param _accessControl Address of LoanAccessControl contract
     * @param _auditRegistry Address of AuditRegistry contract
     * @param _loanApplication Address of LoanApplication contract
     * @param _disbursementMethod Address of DisbursementMethod contract
     * @param _admin Address of the admin
     */
    function initialize(
        address _accessControl,
        address _auditRegistry,
        address _loanApplication,
        address _disbursementMethod,
        address _admin
    ) public initializer {
        if (_accessControl == address(0) || 
            _auditRegistry == address(0) || 
            _loanApplication == address(0) ||
            _disbursementMethod == address(0) ||
            _admin == address(0)) {
            revert ZeroAddress();
        }

        __AccessControl_init();
        __ReentrancyGuard_init();
        __Pausable_init();
        __UUPSUpgradeable_init();

        accessControl = ILoanAccessControl(_accessControl);
        auditRegistry = IAuditRegistry(_auditRegistry);
        loanApplication = ILoanApplication(_loanApplication);
        disbursementMethod = DisbursementMethod(_disbursementMethod);

        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(ADMIN_ROLE, _admin);
        _grantRole(UPGRADER_ROLE, _admin);
    }

    // ============ Core Functions ============

    /**
     * @notice Initiate a disbursement for an approved loan
     * @param loanId Loan identifier
     * @param amount Amount to disburse
     * @return disbursementId The generated disbursement identifier
     */
    function initiateDisbursement(
        bytes32 loanId,
        uint256 amount
    ) external 
        nonReentrant 
        whenNotPaused 
        onlyAuthorized
        returns (bytes32 disbursementId) 
    {
        // Get loan details
        ILoanApplication.Application memory loan = loanApplication.getApplication(loanId);
        
        // Verify loan is approved
        if (loan.status != ILoanApplication.LoanStatus.Approved) {
            revert LoanNotApproved(loanId, loan.status);
        }

        // Check not already disbursed
        if (loanToDisbursement[loanId] != bytes32(0)) {
            bytes32 existingId = loanToDisbursement[loanId];
            DisbursementRecord storage existing = disbursements[existingId];
            if (existing.status == Status.Completed || 
                existing.status == Status.Processing) {
                revert AlreadyDisbursed(loanId);
            }
        }

        // Validate amount
        if (amount == 0 || amount > loan.requestedAmount) {
            revert InvalidAmount(amount, loan.requestedAmount);
        }

        // Get preferred disbursement method
        if (!disbursementMethod.hasPreferredMethod(loanId)) {
            revert NoPreferredMethod(loanId);
        }
        DisbursementMethod.Method method = disbursementMethod.getPreferredMethod(loanId);

        // Lock the method (cannot be changed after disbursement initiated)
        disbursementMethod.lockMethod(loanId);

        // Generate disbursement ID
        _disbursementNonce++;
        disbursementId = keccak256(abi.encodePacked(
            loanId,
            block.timestamp,
            _disbursementNonce
        ));

        // Create disbursement record
        DisbursementRecord storage d = disbursements[disbursementId];
        d.disbursementId = disbursementId;
        d.loanId = loanId;
        d.borrower = loan.borrower;
        d.amount = amount;
        d.method = method;
        d.status = Status.Processing;
        d.processedBy = msg.sender;
        d.initiatedAt = block.timestamp;

        loanToDisbursement[loanId] = disbursementId;
        totalDisbursements++;

        emit DisbursementInitiated(
            disbursementId,
            loanId,
            loan.borrower,
            amount,
            method,
            msg.sender,
            block.timestamp
        );

        // Log to audit registry
        auditRegistry.log(
            disbursementId,
            "disbursement",
            IAuditRegistry.AuditAction.LoanDisbursed,
            keccak256(abi.encodePacked(loanId, amount, uint8(method))),
            bytes32(0),
            bytes32(uint256(Status.Processing))
        );

        return disbursementId;
    }

    /**
     * @notice Complete a disbursement with external reference
     * @param disbursementId Disbursement identifier
     * @param referenceHash Hash of external reference number
     * @return success True if completed successfully
     */
    function completeDisbursement(
        bytes32 disbursementId,
        bytes32 referenceHash
    ) external 
        nonReentrant 
        whenNotPaused 
        onlyAuthorized
        disbursementExists(disbursementId)
        returns (bool success) 
    {
        DisbursementRecord storage d = disbursements[disbursementId];
        
        // Verify status
        if (d.status != Status.Processing) {
            revert InvalidStatus(disbursementId, d.status, Status.Processing);
        }

        // Validate reference
        if (referenceHash == bytes32(0)) {
            revert EmptyHash();
        }
        
        if (usedReferences[referenceHash]) {
            revert DuplicateReference(referenceHash);
        }

        // Update disbursement
        d.status = Status.Completed;
        d.referenceHash = referenceHash;
        d.processedAt = block.timestamp;
        
        usedReferences[referenceHash] = true;
        totalCompleted++;
        totalDisbursedAmount += d.amount;

        // Update loan status to Disbursed
        loanApplication.updateStatus(d.loanId, ILoanApplication.LoanStatus.Disbursed);

        emit DisbursementCompleted(
            disbursementId,
            d.loanId,
            referenceHash,
            msg.sender,
            block.timestamp
        );

        // Log to audit registry
        auditRegistry.log(
            disbursementId,
            "disbursement",
            IAuditRegistry.AuditAction.LoanDisbursed,
            referenceHash,
            bytes32(uint256(Status.Processing)),
            bytes32(uint256(Status.Completed))
        );

        return true;
    }

    /**
     * @notice Cancel a disbursement (for failed transfers)
     * @param disbursementId Disbursement identifier
     * @param reasonHash Hash of cancellation reason
     * @return success True if cancelled successfully
     */
    function cancelDisbursement(
        bytes32 disbursementId,
        bytes32 reasonHash
    ) external 
        nonReentrant 
        whenNotPaused 
        onlyAuthorized
        disbursementExists(disbursementId)
        returns (bool success) 
    {
        DisbursementRecord storage d = disbursements[disbursementId];
        
        // Can only cancel Processing disbursements
        if (d.status != Status.Processing) {
            revert InvalidStatus(disbursementId, d.status, Status.Processing);
        }

        // Validate reason
        if (reasonHash == bytes32(0)) {
            revert EmptyHash();
        }

        // Update disbursement
        d.status = Status.Cancelled;
        d.cancellationReason = reasonHash;
        d.processedAt = block.timestamp;
        
        totalCancelled++;

        // Note: Loan status remains Approved so it can be re-attempted

        emit DisbursementCancelled(
            disbursementId,
            d.loanId,
            reasonHash,
            msg.sender,
            block.timestamp
        );

        // Log to audit registry
        auditRegistry.log(
            disbursementId,
            "disbursement",
            IAuditRegistry.AuditAction.SystemConfigChanged,
            reasonHash,
            bytes32(uint256(Status.Processing)),
            bytes32(uint256(Status.Cancelled))
        );

        return true;
    }

    // ============ View Functions ============

    /**
     * @notice Get disbursement details
     * @param disbursementId Disbursement identifier
     * @return record Complete DisbursementRecord
     */
    function getDisbursement(bytes32 disbursementId) 
        external 
        view 
        disbursementExists(disbursementId)
        returns (DisbursementRecord memory record) 
    {
        return disbursements[disbursementId];
    }

    /**
     * @notice Get disbursement for a loan
     * @param loanId Loan identifier
     * @return record Complete DisbursementRecord
     */
    function getDisbursementByLoan(bytes32 loanId) 
        external 
        view 
        returns (DisbursementRecord memory record) 
    {
        bytes32 disbursementId = loanToDisbursement[loanId];
        if (disbursementId == bytes32(0)) {
            revert DisbursementNotFound(disbursementId);
        }
        return disbursements[disbursementId];
    }

    /**
     * @notice Check if a reference has been used
     * @param referenceHash Reference hash to check
     * @return used True if reference has been used
     */
    function isReferenceUsed(bytes32 referenceHash) 
        external 
        view 
        returns (bool used) 
    {
        return usedReferences[referenceHash];
    }

    /**
     * @notice Check if loan has a disbursement
     * @param loanId Loan identifier
     * @return hasDisbursement True if loan has disbursement
     */
    function hasDisbursement(bytes32 loanId) 
        external 
        view 
        returns (bool hasDisbursement) 
    {
        return loanToDisbursement[loanId] != bytes32(0);
    }

    /**
     * @notice Get system statistics
     * @return _totalDisbursements Total disbursements initiated
     * @return _totalCompleted Total completed disbursements
     * @return _totalCancelled Total cancelled disbursements
     * @return _totalDisbursedAmount Total amount disbursed
     */
    function getStats() 
        external 
        view 
        returns (
            uint256 _totalDisbursements,
            uint256 _totalCompleted,
            uint256 _totalCancelled,
            uint256 _totalDisbursedAmount
        ) 
    {
        return (
            totalDisbursements, 
            totalCompleted,
            totalCancelled,
            totalDisbursedAmount
        );
    }

    // ============ Admin Functions ============

    /**
     * @notice Pause contract (emergency stop)
     */
    function pause() external onlyRole(ADMIN_ROLE) {
        _pause();
    }

    /**
     * @notice Unpause contract
     */
    function unpause() external onlyRole(ADMIN_ROLE) {
        _unpause();
    }

    /**
     * @notice Grant LOAN_OFFICER_ROLE to an address
     * @param account Address to grant role to
     */
    function grantOfficerRole(address account) external onlyRole(ADMIN_ROLE) {
        grantRole(LOAN_OFFICER_ROLE, account);
    }

    /**
     * @notice Revoke LOAN_OFFICER_ROLE from an address
     * @param account Address to revoke role from
     */
    function revokeOfficerRole(address account) external onlyRole(ADMIN_ROLE) {
        revokeRole(LOAN_OFFICER_ROLE, account);
    }

    /**
     * @notice Grant SYSTEM_ROLE to an address
     * @param account Address to grant role to
     */
    function grantSystemRole(address account) external onlyRole(ADMIN_ROLE) {
        grantRole(SYSTEM_ROLE, account);
    }

    /**
     * @notice Revoke SYSTEM_ROLE from an address
     * @param account Address to revoke role from
     */
    function revokeSystemRole(address account) external onlyRole(ADMIN_ROLE) {
        revokeRole(SYSTEM_ROLE, account);
    }

    /**
     * @notice Update DisbursementMethod contract address
     * @param _disbursementMethod New DisbursementMethod contract address
     */
    function setDisbursementMethodContract(address _disbursementMethod) 
        external 
        onlyRole(ADMIN_ROLE) 
    {
        if (_disbursementMethod == address(0)) {
            revert ZeroAddress();
        }
        disbursementMethod = DisbursementMethod(_disbursementMethod);
    }

    // ============ Upgrade Authorization ============

    /**
     * @notice Authorize contract upgrade
     * @param newImplementation Address of new implementation
     */
    function _authorizeUpgrade(address newImplementation) 
        internal 
        override 
        onlyRole(UPGRADER_ROLE) 
    {
        // Intentionally empty - authorization handled by modifier
    }
}
