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
 * @title Repayment
 * @notice Handles loan repayment schedules and payment recording
 * @dev Manages installments and partial payments
 */
contract Repayment is 
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable 
{
    // ============ Type Definitions ============
    enum InstallmentStatus {
        Pending,     // 0 - Not yet due
        Paid,        // 1 - Fully paid
        Partial,     // 2 - Partially paid
        Overdue      // 3 - Past due date
    }

    enum PaymentMethod {
        Cash,           // 0
        BankTransfer,   // 1
        GCash,          // 2
        Check,          // 3
        Wallet          // 4
    }

    struct RepaymentSchedule {
        bytes32 scheduleId;
        bytes32 loanId;
        address borrower;
        uint256 principal;
        uint16 interestRateBps;
        uint16 termMonths;
        uint256 monthlyPayment;
        uint256 totalAmount;
        uint256 totalInterest;
        uint256 totalPaid;
        uint256 startDate;
        uint256 createdAt;
    }

    struct Installment {
        uint16 number;
        uint256 dueDate;
        uint256 principalAmount;
        uint256 interestAmount;
        uint256 totalAmount;
        uint256 paidAmount;
        InstallmentStatus status;
        uint256 paidAt;
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
    uint256 public constant SECONDS_PER_DAY = 86400;
    uint256 public constant DAYS_PER_MONTH = 30;
    
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant LOAN_OFFICER_ROLE = keccak256("LOAN_OFFICER_ROLE");
    bytes32 public constant SYSTEM_ROLE = keccak256("SYSTEM_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ State Variables ============
    ILoanCore public loanCore;
    IAuditRegistry public auditRegistry;

    // Schedule storage
    mapping(bytes32 => RepaymentSchedule) public schedules;
    mapping(bytes32 => mapping(uint16 => Installment)) public installments;
    mapping(bytes32 => bytes32) public loanToSchedule;

    // Payment storage
    mapping(bytes32 => Payment) public payments;
    mapping(bytes32 => bytes32[]) public loanPayments;
    mapping(bytes32 => bool) public usedPaymentReferences;

    // Counters
    uint256 public totalPaymentsRecorded;
    uint256 public totalAmountCollected;
    uint256 private _paymentNonce;

    // ============ Events ============
    event ScheduleCreated(
        bytes32 indexed scheduleId,
        bytes32 indexed loanId,
        address indexed borrower,
        uint256 principal,
        uint16 termMonths,
        uint256 monthlyPayment,
        uint256 totalAmount,
        uint256 timestamp
    );

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
        InstallmentStatus oldStatus,
        InstallmentStatus newStatus,
        uint256 timestamp
    );

    event LoanFullyRepaid(
        bytes32 indexed loanId,
        uint256 totalPaid,
        uint256 timestamp
    );

    event InstallmentOverdue(
        bytes32 indexed loanId,
        uint16 indexed installmentNumber,
        uint256 daysOverdue,
        uint256 timestamp
    );

    // ============ Errors ============
    error ScheduleNotFound(bytes32 loanId);
    error InstallmentNotFound(bytes32 loanId, uint16 number);
    error ScheduleAlreadyExists(bytes32 loanId);
    error InvalidPaymentAmount(uint256 amount);
    error DuplicatePaymentReference(bytes32 referenceHash);
    error LoanNotDisbursed(bytes32 loanId);

    // ============ Modifiers ============
    modifier scheduleExists(bytes32 loanId) {
        if (loanToSchedule[loanId] == bytes32(0)) {
            revert ScheduleNotFound(loanId);
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
        require(
            _loanCore != address(0) && 
            _auditRegistry != address(0) && 
            admin != address(0),
            "Zero address"
        );

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

    // ============ Schedule Functions ============

    /**
     * @notice Create repayment schedule for a disbursed loan
     * @param loanId Loan identifier
     * @param borrower Borrower address
     * @param principal Principal amount
     * @param interestRateBps Monthly interest rate in basis points
     * @param termMonths Loan term in months
     * @param startDate Start date for repayment (disbursement date)
     */
    function createSchedule(
        bytes32 loanId,
        address borrower,
        uint256 principal,
        uint16 interestRateBps,
        uint16 termMonths,
        uint256 startDate
    ) external 
        nonReentrant 
        whenNotPaused 
        returns (bytes32 scheduleId) 
    {
        require(
            hasRole(SYSTEM_ROLE, msg.sender) || 
            hasRole(ADMIN_ROLE, msg.sender) ||
            hasRole(LOAN_OFFICER_ROLE, msg.sender),
            "Repayment: not authorized"
        );

        if (loanToSchedule[loanId] != bytes32(0)) {
            revert ScheduleAlreadyExists(loanId);
        }

        // Verify loan is disbursed
        ILoanCore.LoanStatus status = loanCore.getLoanStatus(loanId);
        if (status != ILoanCore.LoanStatus.Disbursed) {
            revert LoanNotDisbursed(loanId);
        }

        require(borrower != address(0), "Repayment: zero borrower address");
        require(principal > 0, "Repayment: invalid principal");
        require(termMonths > 0 && termMonths <= 360, "Repayment: invalid term");

        // Calculate schedule
        uint256 monthlyInterest = (principal * interestRateBps) / 10000;
        uint256 totalInterest = monthlyInterest * termMonths;
        uint256 monthlyPrincipal = principal / termMonths;
        uint256 monthlyPayment = monthlyPrincipal + monthlyInterest;
        uint256 totalAmount = principal + totalInterest;

        // Generate schedule ID
        scheduleId = keccak256(abi.encodePacked(loanId, block.timestamp));

        // Create schedule
        RepaymentSchedule storage schedule = schedules[scheduleId];
        schedule.scheduleId = scheduleId;
        schedule.loanId = loanId;
        schedule.borrower = borrower;
        schedule.principal = principal;
        schedule.interestRateBps = interestRateBps;
        schedule.termMonths = termMonths;
        schedule.monthlyPayment = monthlyPayment;
        schedule.totalAmount = totalAmount;
        schedule.totalInterest = totalInterest;
        schedule.startDate = startDate;
        schedule.createdAt = block.timestamp;

        loanToSchedule[loanId] = scheduleId;

        // Generate installments
        for (uint16 i = 1; i <= termMonths; i++) {
            uint256 dueDate = startDate + (uint256(i) * DAYS_PER_MONTH * SECONDS_PER_DAY);
            
            Installment storage inst = installments[scheduleId][i];
            inst.number = i;
            inst.dueDate = dueDate;
            inst.principalAmount = monthlyPrincipal;
            inst.interestAmount = monthlyInterest;
            inst.totalAmount = monthlyPayment;
            inst.status = InstallmentStatus.Pending;
        }

        emit ScheduleCreated(
            scheduleId,
            loanId,
            borrower,
            principal,
            termMonths,
            monthlyPayment,
            totalAmount,
            block.timestamp
        );

        return scheduleId;
    }

    // ============ Payment Functions ============

    /**
     * @notice Record a payment for a loan installment
     * @param loanId Loan identifier
     * @param installmentNumber Installment number
     * @param amount Payment amount
     * @param method Payment method
     * @param referenceHash Hash of payment reference
     */
    function recordPayment(
        bytes32 loanId,
        uint16 installmentNumber,
        uint256 amount,
        PaymentMethod method,
        bytes32 referenceHash
    ) external 
        nonReentrant 
        whenNotPaused 
        scheduleExists(loanId)
        returns (bytes32 paymentId) 
    {
        require(
            hasRole(LOAN_OFFICER_ROLE, msg.sender) || 
            hasRole(SYSTEM_ROLE, msg.sender),
            "Repayment: not authorized"
        );

        if (amount == 0) {
            revert InvalidPaymentAmount(amount);
        }

        if (usedPaymentReferences[referenceHash]) {
            revert DuplicatePaymentReference(referenceHash);
        }

        bytes32 scheduleId = loanToSchedule[loanId];
        RepaymentSchedule storage schedule = schedules[scheduleId];
        Installment storage inst = installments[scheduleId][installmentNumber];

        if (inst.number == 0) {
            revert InstallmentNotFound(loanId, installmentNumber);
        }

        require(
            inst.status != InstallmentStatus.Paid,
            "Repayment: already fully paid"
        );

        // Update installment
        InstallmentStatus oldStatus = inst.status;
        inst.paidAmount += amount;

        if (inst.paidAmount >= inst.totalAmount) {
            inst.status = InstallmentStatus.Paid;
            inst.paidAt = block.timestamp;
        } else if (inst.paidAmount > 0) {
            inst.status = InstallmentStatus.Partial;
        }

        // Update schedule totals
        schedule.totalPaid += amount;

        // Generate payment ID
        _paymentNonce++;
        paymentId = keccak256(abi.encodePacked(loanId, installmentNumber, _paymentNonce));

        // Create payment record
        Payment storage payment = payments[paymentId];
        payment.paymentId = paymentId;
        payment.loanId = loanId;
        payment.scheduleId = scheduleId;
        payment.installmentNumber = installmentNumber;
        payment.amount = amount;
        payment.method = method;
        payment.referenceHash = referenceHash;
        payment.recordedBy = msg.sender;
        payment.recordedAt = block.timestamp;

        loanPayments[loanId].push(paymentId);
        usedPaymentReferences[referenceHash] = true;
        totalPaymentsRecorded++;
        totalAmountCollected += amount;

        uint256 remainingBalance = _getRemainingBalance(scheduleId);

        emit PaymentRecorded(
            paymentId,
            loanId,
            installmentNumber,
            amount,
            remainingBalance,
            msg.sender,
            block.timestamp
        );

        if (oldStatus != inst.status) {
            emit InstallmentStatusChanged(
                loanId,
                installmentNumber,
                oldStatus,
                inst.status,
                block.timestamp
            );
        }

        // Audit log
        auditRegistry.log(
            paymentId,
            "payment",
            IAuditRegistry.AuditAction.PaymentRecorded,
            keccak256(abi.encodePacked(loanId, amount, referenceHash)),
            bytes32(uint256(oldStatus)),
            bytes32(uint256(inst.status))
        );

        // Check if loan is fully repaid
        if (remainingBalance == 0) {
            _completeLoan(loanId, scheduleId);
        }

        return paymentId;
    }

    /**
     * @notice Mark an installment as overdue
     * @param loanId Loan identifier
     * @param installmentNumber Installment number
     */
    function markOverdue(
        bytes32 loanId,
        uint16 installmentNumber
    ) external 
        nonReentrant
        whenNotPaused
        scheduleExists(loanId) 
        returns (bool) 
    {
        require(
            hasRole(SYSTEM_ROLE, msg.sender) || hasRole(ADMIN_ROLE, msg.sender),
            "Repayment: not authorized"
        );

        bytes32 scheduleId = loanToSchedule[loanId];
        Installment storage inst = installments[scheduleId][installmentNumber];

        require(inst.number != 0, "Repayment: installment not found");
        require(
            inst.status == InstallmentStatus.Pending || inst.status == InstallmentStatus.Partial,
            "Repayment: invalid status for overdue"
        );
        require(block.timestamp > inst.dueDate, "Repayment: not yet overdue");

        InstallmentStatus oldStatus = inst.status;
        uint256 daysOverdue = (block.timestamp - inst.dueDate) / SECONDS_PER_DAY;

        // Mark as overdue
        inst.status = InstallmentStatus.Overdue;

        emit InstallmentOverdue(loanId, installmentNumber, daysOverdue, block.timestamp);
        emit InstallmentStatusChanged(loanId, installmentNumber, oldStatus, inst.status, block.timestamp);

        return true;
    }

    // ============ Internal Functions ============

    function _completeLoan(bytes32 loanId, bytes32 scheduleId) internal {
        RepaymentSchedule storage schedule = schedules[scheduleId];

        emit LoanFullyRepaid(loanId, schedule.totalPaid, block.timestamp);
    }

    function _getRemainingBalance(bytes32 scheduleId) internal view returns (uint256) {
        RepaymentSchedule storage schedule = schedules[scheduleId];
        uint256 totalOwed = schedule.totalAmount;
        if (schedule.totalPaid >= totalOwed) {
            return 0;
        }
        return totalOwed - schedule.totalPaid;
    }

    // ============ View Functions ============

    /**
     * @notice Get schedule details
     */
    function getSchedule(bytes32 loanId) external view returns (RepaymentSchedule memory) {
        bytes32 scheduleId = loanToSchedule[loanId];
        return schedules[scheduleId];
    }

    /**
     * @notice Get installment details
     */
    function getInstallment(bytes32 loanId, uint16 number) external view returns (Installment memory) {
        bytes32 scheduleId = loanToSchedule[loanId];
        return installments[scheduleId][number];
    }

    /**
     * @notice Get all installments for a loan
     */
    function getAllInstallments(bytes32 loanId) external view returns (Installment[] memory) {
        bytes32 scheduleId = loanToSchedule[loanId];
        RepaymentSchedule storage schedule = schedules[scheduleId];
        
        Installment[] memory result = new Installment[](schedule.termMonths);
        for (uint16 i = 1; i <= schedule.termMonths; i++) {
            result[i - 1] = installments[scheduleId][i];
        }
        return result;
    }

    /**
     * @notice Get remaining balance for a loan
     */
    function getRemainingBalance(bytes32 loanId) external view returns (uint256) {
        bytes32 scheduleId = loanToSchedule[loanId];
        return _getRemainingBalance(scheduleId);
    }

    /**
     * @notice Get next pending installment
     */
    function getNextPayment(bytes32 loanId) external view returns (Installment memory) {
        bytes32 scheduleId = loanToSchedule[loanId];
        RepaymentSchedule storage schedule = schedules[scheduleId];
        
        for (uint16 i = 1; i <= schedule.termMonths; i++) {
            Installment storage inst = installments[scheduleId][i];
            if (inst.status != InstallmentStatus.Paid) {
                return inst;
            }
        }
        
        // Return empty installment if all paid
        Installment memory empty;
        return empty;
    }

    /**
     * @notice Get payment history for a loan
     */
    function getPaymentHistory(bytes32 loanId) external view returns (bytes32[] memory) {
        return loanPayments[loanId];
    }

    /**
     * @notice Get payment details
     */
    function getPayment(bytes32 paymentId) external view returns (Payment memory) {
        return payments[paymentId];
    }

    /**
     * @notice Get paid installments count
     */
    function getPaidCount(bytes32 loanId) external view returns (uint256) {
        bytes32 scheduleId = loanToSchedule[loanId];
        RepaymentSchedule storage schedule = schedules[scheduleId];
        
        uint256 count = 0;
        for (uint16 i = 1; i <= schedule.termMonths; i++) {
            if (installments[scheduleId][i].status == InstallmentStatus.Paid) {
                count++;
            }
        }
        return count;
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
