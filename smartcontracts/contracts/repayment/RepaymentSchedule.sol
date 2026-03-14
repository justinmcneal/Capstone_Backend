// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import "../interfaces/ILoanCore.sol";

/**
 * @title RepaymentSchedule
 * @notice Schedule generation and structure for loan repayments
 * @dev Refactored from Repayment.sol — handles only schedule creation and read operations.
 *      Payment recording lives in a separate contract.
 * @custom:security-contact security@msme-platform.com
 */
contract RepaymentSchedule is
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable
{
    // ============ Type Definitions ============

    enum InstallmentStatus {
        Pending,  // 0 — Not yet due
        Paid,     // 1 — Fully paid
        Partial,  // 2 — Partially paid
        Overdue   // 3 — Past due date
    }

    struct Schedule {
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

    /// @dev scheduleId ⇒ Schedule
    mapping(bytes32 => Schedule) public schedules;
    /// @dev scheduleId ⇒ installmentNumber ⇒ Installment
    mapping(bytes32 => mapping(uint16 => Installment)) public installments;
    /// @dev loanId ⇒ scheduleId (one schedule per loan)
    mapping(bytes32 => bytes32) public loanToSchedule;

    // ============ Events ============

    event ScheduleCreated(
        bytes32 indexed scheduleId,
        bytes32 indexed loanId,
        address indexed borrower,
        uint256 principal,
        uint16 termMonths,
        uint256 monthlyPayment,
        uint256 timestamp
    );

    // ============ Errors ============

    error ScheduleAlreadyExists(bytes32 loanId);
    error ScheduleNotFound(bytes32 loanId);
    error LoanNotDisbursed(bytes32 loanId);
    error InstallmentNotFound(bytes32 loanId, uint16 number);
    error InvalidPrincipal();
    error InvalidTerm();
    error ZeroAddress();
    error NotAuthorized(address caller);

    // ============ Modifiers ============

    modifier scheduleExists(bytes32 loanId) {
        if (loanToSchedule[loanId] == bytes32(0)) {
            revert ScheduleNotFound(loanId);
        }
        _;
    }

    modifier onlyAuthorized() {
        if (
            !hasRole(SYSTEM_ROLE, msg.sender) &&
            !hasRole(ADMIN_ROLE, msg.sender) &&
            !hasRole(LOAN_OFFICER_ROLE, msg.sender)
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
     * @notice Initialize the RepaymentSchedule contract
     * @param _loanCore Address of the LoanCore contract
     * @param _admin    Address of the initial admin
     */
    function initialize(
        address _loanCore,
        address _admin
    ) public initializer {
        if (_loanCore == address(0) || _admin == address(0)) {
            revert ZeroAddress();
        }

        __AccessControl_init();
        __ReentrancyGuard_init();
        __Pausable_init();
        __UUPSUpgradeable_init();

        loanCore = ILoanCore(_loanCore);

        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(ADMIN_ROLE, _admin);
        _grantRole(UPGRADER_ROLE, _admin);
    }

    // ============ Schedule Creation ============

    /**
     * @notice Create a repayment schedule for a disbursed loan
     * @param loanId          Loan identifier
     * @param borrower        Borrower address
     * @param principal       Principal amount (wei)
     * @param interestRateBps Monthly interest rate in basis points (e.g. 150 = 1.5 %)
     * @param termMonths      Loan term in months
     * @param startDate       Repayment start date (disbursement timestamp)
     * @return scheduleId     Generated schedule identifier
     */
    function createSchedule(
        bytes32 loanId,
        address borrower,
        uint256 principal,
        uint16 interestRateBps,
        uint16 termMonths,
        uint256 startDate
    )
        external
        nonReentrant
        whenNotPaused
        onlyAuthorized
        returns (bytes32 scheduleId)
    {
        // ── Guards ──────────────────────────────────────────────
        if (loanToSchedule[loanId] != bytes32(0)) {
            revert ScheduleAlreadyExists(loanId);
        }

        ILoanCore.LoanStatus status = loanCore.getLoanStatus(loanId);
        if (status != ILoanCore.LoanStatus.Disbursed) {
            revert LoanNotDisbursed(loanId);
        }

        if (principal == 0) {
            revert InvalidPrincipal();
        }
        if (termMonths == 0 || termMonths > 360) {
            revert InvalidTerm();
        }

        // ── Calculation (flat-rate, mirrors backend) ────────────
        uint256 monthlyInterest  = (principal * interestRateBps) / 10_000;
        uint256 totalInterest    = monthlyInterest * termMonths;
        uint256 monthlyPrincipal = principal / termMonths;
        uint256 monthlyPayment   = monthlyPrincipal + monthlyInterest;
        uint256 totalAmount      = principal + totalInterest;

        // ── Generate schedule ID ────────────────────────────────
        scheduleId = keccak256(abi.encodePacked(loanId, block.timestamp));

        // ── Persist schedule ────────────────────────────────────
        Schedule storage sched = schedules[scheduleId];
        sched.scheduleId     = scheduleId;
        sched.loanId         = loanId;
        sched.borrower       = borrower;
        sched.principal      = principal;
        sched.interestRateBps = interestRateBps;
        sched.termMonths     = termMonths;
        sched.monthlyPayment = monthlyPayment;
        sched.totalAmount    = totalAmount;
        sched.totalInterest  = totalInterest;
        sched.startDate      = startDate;
        sched.createdAt      = block.timestamp;

        loanToSchedule[loanId] = scheduleId;

        // ── Generate installments (30-day months) ───────────────
        for (uint16 i = 1; i <= termMonths; i++) {
            uint256 dueDate = startDate + (uint256(i) * DAYS_PER_MONTH * SECONDS_PER_DAY);

            Installment storage inst = installments[scheduleId][i];
            inst.number          = i;
            inst.dueDate         = dueDate;
            inst.principalAmount = monthlyPrincipal;
            inst.interestAmount  = monthlyInterest;
            inst.totalAmount     = monthlyPayment;
            inst.status          = InstallmentStatus.Pending;
        }

        emit ScheduleCreated(
            scheduleId,
            loanId,
            borrower,
            principal,
            termMonths,
            monthlyPayment,
            block.timestamp
        );

        return scheduleId;
    }

    // ============ View Functions ============

    /**
     * @notice Get schedule details for a loan
     * @param loanId Loan identifier
     * @return The full Schedule struct
     */
    function getSchedule(bytes32 loanId)
        external
        view
        scheduleExists(loanId)
        returns (Schedule memory)
    {
        bytes32 scheduleId = loanToSchedule[loanId];
        return schedules[scheduleId];
    }

    /**
     * @notice Get a single installment
     * @param loanId Loan identifier
     * @param number Installment number (1-based)
     * @return The Installment struct
     */
    function getInstallment(bytes32 loanId, uint16 number)
        external
        view
        scheduleExists(loanId)
        returns (Installment memory)
    {
        bytes32 scheduleId = loanToSchedule[loanId];
        Installment storage inst = installments[scheduleId][number];
        if (inst.number == 0) {
            revert InstallmentNotFound(loanId, number);
        }
        return inst;
    }

    /**
     * @notice Get all installments for a loan
     * @param loanId Loan identifier
     * @return result Array of Installment structs
     */
    function getAllInstallments(bytes32 loanId)
        external
        view
        scheduleExists(loanId)
        returns (Installment[] memory result)
    {
        bytes32 scheduleId = loanToSchedule[loanId];
        Schedule storage sched = schedules[scheduleId];

        result = new Installment[](sched.termMonths);
        for (uint16 i = 1; i <= sched.termMonths; i++) {
            result[i - 1] = installments[scheduleId][i];
        }
        return result;
    }

    /**
     * @notice Get the remaining balance for a loan
     * @param loanId Loan identifier
     * @return Remaining amount owed (totalAmount − totalPaid)
     */
    function getRemainingBalance(bytes32 loanId)
        external
        view
        scheduleExists(loanId)
        returns (uint256)
    {
        bytes32 scheduleId = loanToSchedule[loanId];
        Schedule storage sched = schedules[scheduleId];
        if (sched.totalPaid >= sched.totalAmount) {
            return 0;
        }
        return sched.totalAmount - sched.totalPaid;
    }

    // ============ Admin / Emergency Functions ============

    function pause() external onlyRole(ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(ADMIN_ROLE) {
        _unpause();
    }

    /**
     * @notice Update the LoanCore contract reference
     */
    function setLoanCore(address _loanCore) external onlyRole(ADMIN_ROLE) {
        if (_loanCore == address(0)) revert ZeroAddress();
        loanCore = ILoanCore(_loanCore);
    }

    // ============ Cross-Contract Mutators (SYSTEM_ROLE only) ============

    /**
     * @notice Apply a payment to an installment — called by PaymentRecording
     * @param loanId             Loan identifier
     * @param installmentNumber  Installment number (1-based)
     * @param amount             Payment amount to apply
     * @return oldStatus         Status before the payment
     * @return newStatus         Status after the payment
     */
    function applyPayment(
        bytes32 loanId,
        uint16 installmentNumber,
        uint256 amount
    )
        external
        onlyRole(SYSTEM_ROLE)
        scheduleExists(loanId)
        returns (InstallmentStatus oldStatus, InstallmentStatus newStatus)
    {
        bytes32 scheduleId = loanToSchedule[loanId];
        Installment storage inst = installments[scheduleId][installmentNumber];
        if (inst.number == 0) {
            revert InstallmentNotFound(loanId, installmentNumber);
        }

        oldStatus = inst.status;
        inst.paidAmount += amount;

        if (inst.paidAmount >= inst.totalAmount) {
            inst.status = InstallmentStatus.Paid;
            inst.paidAt = block.timestamp;
        } else if (inst.paidAmount > 0) {
            inst.status = InstallmentStatus.Partial;
        }
        newStatus = inst.status;

        // Update schedule totals
        Schedule storage sched = schedules[scheduleId];
        sched.totalPaid += amount;
    }

    /**
     * @notice Mark an installment as overdue — called by PaymentRecording
     * @param loanId             Loan identifier
     * @param installmentNumber  Installment number (1-based)
     * @return oldStatus         Status before marking overdue
     * @return daysOverdue       Number of days past due
     */
    function setInstallmentOverdue(
        bytes32 loanId,
        uint16 installmentNumber
    )
        external
        onlyRole(SYSTEM_ROLE)
        scheduleExists(loanId)
        returns (InstallmentStatus oldStatus, uint256 daysOverdue)
    {
        bytes32 scheduleId = loanToSchedule[loanId];
        Installment storage inst = installments[scheduleId][installmentNumber];
        if (inst.number == 0) {
            revert InstallmentNotFound(loanId, installmentNumber);
        }

        oldStatus = inst.status;
        daysOverdue = (block.timestamp - inst.dueDate) / SECONDS_PER_DAY;

        inst.status = InstallmentStatus.Overdue;
    }

    // ============ Upgrade Authorization ============

    function _authorizeUpgrade(address newImplementation)
        internal
        override
        onlyRole(UPGRADER_ROLE)
    {}
}
