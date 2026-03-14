// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import "../interfaces/IAuditRegistry.sol";
import "./RepaymentSchedule.sol";

/**
 * @title PaymentRecording
 * @notice Payment recording and installment status updates for loan repayments
 * @dev Refactored from Repayment.sol — handles payment recording, overdue marking,
 *      and payment history. Delegates schedule/installment state mutations to RepaymentSchedule.
 * @custom:security-contact security@msme-platform.com
 */
contract PaymentRecording is
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable
{
    // ============ Type Definitions ============

    enum PaymentMethod {
        Cash,           // 0
        BankTransfer,   // 1
        GCash,          // 2
        Maya,           // 3
        Other           // 4
    }

    struct Payment {
        bytes32 paymentId;
        bytes32 loanId;
        bytes32 scheduleId;
        uint16 installmentNumber;
        uint256 amount;
        PaymentMethod method;
        bytes32 referenceHash;
        address recordedBy;
        uint256 recordedAt;
    }

    // ============ Constants ============

    uint256 public constant VERSION = 1;

    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant LOAN_OFFICER_ROLE = keccak256("LOAN_OFFICER_ROLE");
    bytes32 public constant SYSTEM_ROLE = keccak256("SYSTEM_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ State Variables ============

    RepaymentSchedule public repaymentSchedule;
    IAuditRegistry public auditRegistry;

    /// @dev paymentId ⇒ Payment
    mapping(bytes32 => Payment) public payments;
    /// @dev loanId ⇒ paymentId[]
    mapping(bytes32 => bytes32[]) public loanPayments;
    /// @dev referenceHash ⇒ used
    mapping(bytes32 => bool) public usedPaymentReferences;

    // Counters
    uint256 public totalPaymentsRecorded;
    uint256 public totalAmountCollected;
    uint256 private _paymentNonce;

    // ============ Events ============

    event PaymentRecorded(
        bytes32 indexed paymentId,
        bytes32 indexed loanId,
        uint16 indexed installmentNumber,
        uint256 amount,
        uint256 remainingBalance,
        address recordedBy,
        uint256 timestamp
    );

    event InstallmentStatusChanged(
        bytes32 indexed loanId,
        uint16 indexed installmentNumber,
        RepaymentSchedule.InstallmentStatus oldStatus,
        RepaymentSchedule.InstallmentStatus newStatus,
        uint256 timestamp
    );

    event InstallmentOverdue(
        bytes32 indexed loanId,
        uint16 indexed installmentNumber,
        uint256 daysOverdue,
        uint256 timestamp
    );

    event LoanFullyRepaid(
        bytes32 indexed loanId,
        uint256 totalPaid,
        uint256 timestamp
    );

    // ============ Errors ============

    error InvalidPaymentAmount(uint256 amount);
    error DuplicatePaymentReference(bytes32 referenceHash);
    error InstallmentAlreadyPaid(bytes32 loanId, uint16 number);
    error InstallmentNotFound(bytes32 loanId, uint16 number);
    error NotYetOverdue(bytes32 loanId, uint16 number);
    error InvalidOverdueStatus(bytes32 loanId, uint16 number);
    error PaymentNotFound(bytes32 paymentId);
    error ZeroAddress();
    error NotAuthorized(address caller);

    // ============ Modifiers ============

    modifier onlyPaymentAuthorized() {
        if (
            !hasRole(LOAN_OFFICER_ROLE, msg.sender) &&
            !hasRole(SYSTEM_ROLE, msg.sender)
        ) {
            revert NotAuthorized(msg.sender);
        }
        _;
    }

    modifier onlyOverdueAuthorized() {
        if (
            !hasRole(SYSTEM_ROLE, msg.sender) &&
            !hasRole(ADMIN_ROLE, msg.sender)
        ) {
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
     * @notice Initialize the PaymentRecording contract
     * @param _repaymentSchedule Address of the RepaymentSchedule contract
     * @param _auditRegistry     Address of the AuditRegistry contract
     * @param _admin             Address of the initial admin
     */
    function initialize(
        address _repaymentSchedule,
        address _auditRegistry,
        address _admin
    ) public initializer {
        if (
            _repaymentSchedule == address(0) ||
            _auditRegistry == address(0) ||
            _admin == address(0)
        ) {
            revert ZeroAddress();
        }

        __AccessControl_init();
        __ReentrancyGuard_init();
        __Pausable_init();
        __UUPSUpgradeable_init();

        repaymentSchedule = RepaymentSchedule(_repaymentSchedule);
        auditRegistry = IAuditRegistry(_auditRegistry);

        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(ADMIN_ROLE, _admin);
        _grantRole(UPGRADER_ROLE, _admin);
    }

    // ============ Payment Functions ============

    /**
     * @notice Record a payment for a loan installment
     * @param loanId             Loan identifier
     * @param installmentNumber  Installment number (1-based)
     * @param amount             Payment amount
     * @param method             Payment method enum
     * @param referenceHash      Hash of payment reference (must be unique)
     * @return paymentId         Generated payment identifier
     */
    function recordPayment(
        bytes32 loanId,
        uint16 installmentNumber,
        uint256 amount,
        PaymentMethod method,
        bytes32 referenceHash
    )
        external
        nonReentrant
        whenNotPaused
        onlyPaymentAuthorized
        returns (bytes32 paymentId)
    {
        // ── Guards ──────────────────────────────────────────────
        if (amount == 0) {
            revert InvalidPaymentAmount(amount);
        }
        if (usedPaymentReferences[referenceHash]) {
            revert DuplicatePaymentReference(referenceHash);
        }

        // Read installment from schedule to validate
        RepaymentSchedule.Installment memory inst = repaymentSchedule.getInstallment(loanId, installmentNumber);

        if (inst.status == RepaymentSchedule.InstallmentStatus.Paid) {
            revert InstallmentAlreadyPaid(loanId, installmentNumber);
        }

        // ── Apply payment to schedule (mutates RepaymentSchedule state) ──
        (
            RepaymentSchedule.InstallmentStatus oldStatus,
            RepaymentSchedule.InstallmentStatus newStatus
        ) = repaymentSchedule.applyPayment(loanId, installmentNumber, amount);

        // ── Generate payment ID ─────────────────────────────────
        _paymentNonce++;
        paymentId = keccak256(abi.encodePacked(loanId, installmentNumber, _paymentNonce));

        // ── Get schedule details for the payment record ─────────
        RepaymentSchedule.Schedule memory sched = repaymentSchedule.getSchedule(loanId);

        // ── Persist payment ─────────────────────────────────────
        Payment storage payment = payments[paymentId];
        payment.paymentId         = paymentId;
        payment.loanId            = loanId;
        payment.scheduleId        = sched.scheduleId;
        payment.installmentNumber = installmentNumber;
        payment.amount            = amount;
        payment.method            = method;
        payment.referenceHash     = referenceHash;
        payment.recordedBy        = msg.sender;
        payment.recordedAt        = block.timestamp;

        loanPayments[loanId].push(paymentId);
        usedPaymentReferences[referenceHash] = true;
        totalPaymentsRecorded++;
        totalAmountCollected += amount;

        // ── Remaining balance ───────────────────────────────────
        uint256 remainingBalance = repaymentSchedule.getRemainingBalance(loanId);

        emit PaymentRecorded(
            paymentId,
            loanId,
            installmentNumber,
            amount,
            remainingBalance,
            msg.sender,
            block.timestamp
        );

        if (oldStatus != newStatus) {
            emit InstallmentStatusChanged(
                loanId,
                installmentNumber,
                oldStatus,
                newStatus,
                block.timestamp
            );
        }

        // ── Audit log ──────────────────────────────────────────
        auditRegistry.log(
            paymentId,
            "payment",
            IAuditRegistry.AuditAction.PaymentRecorded,
            keccak256(abi.encodePacked(loanId, amount, referenceHash)),
            bytes32(uint256(oldStatus)),
            bytes32(uint256(newStatus))
        );

        // ── Fully repaid? ──────────────────────────────────────
        if (remainingBalance == 0) {
            emit LoanFullyRepaid(loanId, sched.totalPaid + amount, block.timestamp);
        }

        return paymentId;
    }

    // ============ Overdue Functions ============

    /**
     * @notice Mark an installment as overdue
     * @param loanId             Loan identifier
     * @param installmentNumber  Installment number (1-based)
     * @return True on success
     */
    function markOverdue(
        bytes32 loanId,
        uint16 installmentNumber
    )
        external
        whenNotPaused
        onlyOverdueAuthorized
        returns (bool)
    {
        // Read installment to validate preconditions
        RepaymentSchedule.Installment memory inst = repaymentSchedule.getInstallment(loanId, installmentNumber);

        if (
            inst.status != RepaymentSchedule.InstallmentStatus.Pending &&
            inst.status != RepaymentSchedule.InstallmentStatus.Partial
        ) {
            revert InvalidOverdueStatus(loanId, installmentNumber);
        }

        if (block.timestamp <= inst.dueDate) {
            revert NotYetOverdue(loanId, installmentNumber);
        }

        // Delegate state mutation to RepaymentSchedule
        (
            RepaymentSchedule.InstallmentStatus oldStatus,
            uint256 daysOverdue
        ) = repaymentSchedule.setInstallmentOverdue(loanId, installmentNumber);

        emit InstallmentOverdue(loanId, installmentNumber, daysOverdue, block.timestamp);
        emit InstallmentStatusChanged(
            loanId,
            installmentNumber,
            oldStatus,
            RepaymentSchedule.InstallmentStatus.Overdue,
            block.timestamp
        );

        return true;
    }

    // ============ View Functions ============

    /**
     * @notice Get payment history (IDs) for a loan
     * @param loanId Loan identifier
     * @return Array of Payment structs
     */
    function getPaymentHistory(bytes32 loanId)
        external
        view
        returns (Payment[] memory)
    {
        bytes32[] memory ids = loanPayments[loanId];
        Payment[] memory result = new Payment[](ids.length);
        for (uint256 i = 0; i < ids.length; i++) {
            result[i] = payments[ids[i]];
        }
        return result;
    }

    /**
     * @notice Get a single payment record
     * @param paymentId Payment identifier
     * @return The Payment struct
     */
    function getPayment(bytes32 paymentId)
        external
        view
        returns (Payment memory)
    {
        if (payments[paymentId].recordedAt == 0) {
            revert PaymentNotFound(paymentId);
        }
        return payments[paymentId];
    }

    /**
     * @notice Get raw payment IDs for a loan
     * @param loanId Loan identifier
     * @return Array of payment IDs
     */
    function getPaymentIds(bytes32 loanId)
        external
        view
        returns (bytes32[] memory)
    {
        return loanPayments[loanId];
    }

    // ============ Admin / Emergency Functions ============

    function pause() external onlyRole(ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(ADMIN_ROLE) {
        _unpause();
    }

    /**
     * @notice Update the RepaymentSchedule contract reference
     */
    function setRepaymentSchedule(address _repaymentSchedule) external onlyRole(ADMIN_ROLE) {
        if (_repaymentSchedule == address(0)) revert ZeroAddress();
        repaymentSchedule = RepaymentSchedule(_repaymentSchedule);
    }

    /**
     * @notice Update the AuditRegistry contract reference
     */
    function setAuditRegistry(address _auditRegistry) external onlyRole(ADMIN_ROLE) {
        if (_auditRegistry == address(0)) revert ZeroAddress();
        auditRegistry = IAuditRegistry(_auditRegistry);
    }

    // ============ Upgrade Authorization ============

    function _authorizeUpgrade(address newImplementation)
        internal
        override
        onlyRole(UPGRADER_ROLE)
    {}
}
