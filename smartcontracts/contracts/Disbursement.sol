// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import "./interfaces/ILoanCore.sol";
import "./interfaces/IAuditRegistry.sol";

/**
 * @title Disbursement
 * @notice Handles loan disbursement process
 * @dev Tracks disbursement status and supports reversals
 */
contract Disbursement is 
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable 
{
    // ============ Type Definitions ============
    enum DisbursementStatus {
        Pending,         // 0 - Awaiting disbursement
        Processing,      // 1 - In progress
        Completed        // 2 - Successfully disbursed
    }

    enum DisbursementMethod {
        BankTransfer,    // 0
        Cash,            // 1
        GCash,           // 2
        Maya,            // 3
        Other            // 4
    }

    struct DisbursementRecord {
        bytes32 disbursementId;
        bytes32 loanId;
        address borrower;
        uint256 amount;
        DisbursementMethod method;
        bytes32 referenceHash;           // Hash of external reference number
        DisbursementStatus status;
        address processedBy;             // Officer who processed
        uint256 initiatedAt;
        uint256 processedAt;
    }

    // ============ Constants ============
    uint256 public constant VERSION = 1;
    
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant LOAN_OFFICER_ROLE = keccak256("LOAN_OFFICER_ROLE");
    bytes32 public constant SYSTEM_ROLE = keccak256("SYSTEM_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ State Variables ============
    ILoanCore public loanCore;
    IAuditRegistry public auditRegistry;

    // Disbursement storage
    mapping(bytes32 => DisbursementRecord) public disbursements;
    mapping(bytes32 => bytes32) public loanToDisbursement;  // loanId => disbursementId
    mapping(bytes32 => bool) public usedReferences;         // Prevent duplicate references
    
    // Counters
    uint256 public totalDisbursements;
    uint256 public totalDisbursedAmount;
    uint256 private _disbursementNonce;

    // ============ Events ============
    event DisbursementInitiated(
        bytes32 indexed disbursementId,
        bytes32 indexed loanId,
        address indexed borrower,
        uint256 amount,
        DisbursementMethod method,
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

    // ============ Errors ============
    error DisbursementNotFound(bytes32 disbursementId);
    error InvalidDisbursementStatus(bytes32 disbursementId, DisbursementStatus current, DisbursementStatus expected);
    error DuplicateReference(bytes32 referenceHash);
    error LoanNotApproved(bytes32 loanId);
    error AlreadyDisbursed(bytes32 loanId);

    // ============ Modifiers ============
    modifier disbursementExists(bytes32 disbursementId) {
        if (disbursements[disbursementId].initiatedAt == 0) {
            revert DisbursementNotFound(disbursementId);
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
     */
    function initialize(
        address _loanCore,
        address _auditRegistry,
        address admin
    ) public initializer {
        require(_loanCore != address(0) && _auditRegistry != address(0) && admin != address(0), "Zero address");

        __AccessControl_init();
        __ReentrancyGuard_init();
        __Pausable_init();
        __UUPSUpgradeable_init();

        loanCore = ILoanCore(_loanCore);
        auditRegistry = IAuditRegistry(_auditRegistry);

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        _grantRole(UPGRADER_ROLE, admin);
    }

    // ============ Disbursement Functions ============

    /**
     * @notice Initiate a disbursement for an approved loan
     * @param loanId Loan identifier
     * @param amount Amount to disburse
     * @param method Disbursement method
     */
    function initiateDisbursement(
        bytes32 loanId,
        uint256 amount,
        DisbursementMethod method
    ) external 
        nonReentrant 
        whenNotPaused 
        returns (bytes32 disbursementId) 
    {
        require(
            hasRole(LOAN_OFFICER_ROLE, msg.sender) || hasRole(ADMIN_ROLE, msg.sender),
            "Disbursement: not authorized"
        );

        // Verify loan is approved
        ILoanCore.Loan memory loan = loanCore.getLoan(loanId);
        if (loan.status != ILoanCore.LoanStatus.Approved) {
            revert LoanNotApproved(loanId);
        }

        // Check not already disbursed
        if (loanToDisbursement[loanId] != bytes32(0)) {
            bytes32 existingId = loanToDisbursement[loanId];
            DisbursementRecord storage existing = disbursements[existingId];
            if (existing.status == DisbursementStatus.Completed || existing.status == DisbursementStatus.Pending || existing.status == DisbursementStatus.Processing) {
                revert AlreadyDisbursed(loanId);
            }
        }

        require(amount > 0 && amount <= loan.approvedAmount, "Disbursement: invalid amount");

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
        d.status = DisbursementStatus.Processing;
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

        return disbursementId;
    }

    /**
     * @notice Complete a disbursement with external reference
     * @param disbursementId Disbursement identifier
     * @param referenceHash Hash of external reference number
     */
    function completeDisbursement(
        bytes32 disbursementId,
        bytes32 referenceHash
    ) external 
        nonReentrant 
        whenNotPaused 
        disbursementExists(disbursementId)
        returns (bool) 
    {
        require(
            hasRole(LOAN_OFFICER_ROLE, msg.sender) || 
            hasRole(ADMIN_ROLE, msg.sender) || 
            hasRole(SYSTEM_ROLE, msg.sender),
            "Disbursement: not authorized"
        );

        DisbursementRecord storage d = disbursements[disbursementId];
        
        if (d.status != DisbursementStatus.Processing) {
            revert InvalidDisbursementStatus(disbursementId, d.status, DisbursementStatus.Processing);
        }

        require(referenceHash != bytes32(0), "Disbursement: reference required");
        
        if (usedReferences[referenceHash]) {
            revert DuplicateReference(referenceHash);
        }

        // Update disbursement
        d.status = DisbursementStatus.Completed;
        d.referenceHash = referenceHash;
        d.processedAt = block.timestamp;
        
        usedReferences[referenceHash] = true;
        totalDisbursedAmount += d.amount;

        // Update loan status in LoanCore
        loanCore.markDisbursed(d.loanId, d.amount);

        emit DisbursementCompleted(
            disbursementId,
            d.loanId,
            referenceHash,
            msg.sender,
            block.timestamp
        );

        // Audit log
        auditRegistry.log(
            disbursementId,
            "disbursement",
            IAuditRegistry.AuditAction.LoanDisbursed,
            keccak256(abi.encodePacked(d.loanId, d.amount, referenceHash)),
            bytes32(uint256(DisbursementStatus.Processing)),
            bytes32(uint256(DisbursementStatus.Completed))
        );

        return true;
    }

    // ============ View Functions ============

    /**
     * @notice Get disbursement details
     */
    function getDisbursement(bytes32 disbursementId) external view returns (DisbursementRecord memory) {
        return disbursements[disbursementId];
    }

    /**
     * @notice Get disbursement for a loan
     */
    function getDisbursementByLoan(bytes32 loanId) external view returns (DisbursementRecord memory) {
        bytes32 disbursementId = loanToDisbursement[loanId];
        return disbursements[disbursementId];
    }

    /**
     * @notice Check if a reference has been used
     */
    function isReferenceUsed(bytes32 referenceHash) external view returns (bool) {
        return usedReferences[referenceHash];
    }

    /**
     * @notice Get system statistics
     */
    function getStats() external view returns (
        uint256 _totalDisbursements,
        uint256 _totalDisbursedAmount
    ) {
        return (totalDisbursements, totalDisbursedAmount);
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
