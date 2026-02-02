// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import "./interfaces/ILoanCore.sol";
import "./interfaces/IAuditRegistry.sol";

/**
 * @title TokenRepayment
 * @notice Handles actual ERC20 token transfers for loan repayments
 * @dev Borrowers transfer tokens to repay their loans
 * 
 * Flow:
 * 1. Borrower approves this contract to spend their tokens
 * 2. Borrower calls repay() with loan ID and amount
 * 3. Tokens are transferred from borrower to treasury
 * 4. Payment is recorded on-chain
 */
contract TokenRepayment is 
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable 
{
    using SafeERC20 for IERC20;

    // ============ Type Definitions ============
    struct PaymentRecord {
        bytes32 paymentId;
        bytes32 loanId;
        address payer;
        uint256 amount;
        uint256 timestamp;
        bool isPartial;
    }

    // ============ Constants ============
    uint256 public constant VERSION = 1;
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant LOAN_OFFICER_ROLE = keccak256("LOAN_OFFICER_ROLE");
    bytes32 public constant SYSTEM_ROLE = keccak256("SYSTEM_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ State Variables ============
    IERC20 public loanToken;
    ILoanCore public loanCore;
    IAuditRegistry public auditRegistry;
    address public treasury;

    // Payment storage
    mapping(bytes32 => PaymentRecord[]) public loanPayments;  // loanId => payments
    mapping(bytes32 => uint256) public totalPaidByLoan;       // loanId => total paid
    mapping(bytes32 => bool) public usedPaymentIds;           // Prevent duplicate IDs

    // Counters
    uint256 public totalPaymentsReceived;
    uint256 public totalAmountReceived;
    uint256 private _paymentNonce;

    // ============ Events ============
    event PaymentReceived(
        bytes32 indexed paymentId,
        bytes32 indexed loanId,
        address indexed payer,
        uint256 amount,
        uint256 timestamp
    );

    event FullyRepaid(
        bytes32 indexed loanId,
        uint256 totalPaid,
        uint256 timestamp
    );

    event OverpaymentRefunded(
        bytes32 indexed loanId,
        address indexed payer,
        uint256 refundAmount,
        uint256 timestamp
    );

    // ============ Errors ============
    error InvalidLoanStatus();
    error ZeroAmount();
    error ZeroAddress();
    error DuplicatePaymentId();
    error LoanNotFound();
    error NotBorrower();

    // ============ Initializer ============

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /**
     * @notice Initialize the contract
     * @param _loanToken Address of the ERC20 loan token
     * @param _loanCore Address of LoanCore contract
     * @param _auditRegistry Address of AuditRegistry contract
     * @param _treasury Address of the treasury
     * @param _admin Admin address
     */
    function initialize(
        address _loanToken,
        address _loanCore,
        address _auditRegistry,
        address _treasury,
        address _admin
    ) public initializer {
        if (_loanToken == address(0) || _loanCore == address(0) || 
            _treasury == address(0) || _admin == address(0)) {
            revert ZeroAddress();
        }

        __AccessControl_init();
        __ReentrancyGuard_init();
        __Pausable_init();
        __UUPSUpgradeable_init();

        loanToken = IERC20(_loanToken);
        loanCore = ILoanCore(_loanCore);
        auditRegistry = IAuditRegistry(_auditRegistry);
        treasury = _treasury;

        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(ADMIN_ROLE, _admin);
        _grantRole(UPGRADER_ROLE, _admin);
    }

    // ============ Core Functions ============

    /**
     * @notice Make a repayment on a loan
     * @dev Borrower must approve this contract first
     * @param loanId The loan identifier
     * @param amount Amount to pay
     * @return paymentId The generated payment ID
     */
    function repay(bytes32 loanId, uint256 amount) 
        external 
        nonReentrant 
        whenNotPaused 
        returns (bytes32 paymentId)
    {
        if (amount == 0) revert ZeroAmount();

        // Get loan details
        ILoanCore.Loan memory loan = loanCore.getLoan(loanId);
        
        // Verify loan is active (disbursed or in repayment)
        if (loan.status != ILoanCore.LoanStatus.Disbursed && 
            loan.status != ILoanCore.LoanStatus.Active) {
            revert InvalidLoanStatus();
        }

        // Generate unique payment ID
        _paymentNonce++;
        paymentId = keccak256(abi.encodePacked(
            loanId,
            msg.sender,
            amount,
            block.timestamp,
            _paymentNonce
        ));

        // Determine if this is a partial or full payment
        uint256 remainingBalance = _getRemainingBalance(loanId, loan.approvedAmount);
        bool isPartial = amount < remainingBalance;
        uint256 actualPayment = amount;
        uint256 refund = 0;

        // Handle overpayment
        if (amount > remainingBalance) {
            actualPayment = remainingBalance;
            refund = amount - remainingBalance;
        }

        // Update state BEFORE transfer (CEI pattern)
        PaymentRecord memory record = PaymentRecord({
            paymentId: paymentId,
            loanId: loanId,
            payer: msg.sender,
            amount: actualPayment,
            timestamp: block.timestamp,
            isPartial: isPartial && refund == 0
        });

        loanPayments[loanId].push(record);
        totalPaidByLoan[loanId] += actualPayment;
        usedPaymentIds[paymentId] = true;
        totalPaymentsReceived++;
        totalAmountReceived += actualPayment;

        // Transfer payment to treasury
        loanToken.safeTransferFrom(msg.sender, treasury, actualPayment);

        // Refund any overpayment
        if (refund > 0) {
            loanToken.safeTransferFrom(msg.sender, msg.sender, 0); // No-op, tokens stay with sender
            emit OverpaymentRefunded(loanId, msg.sender, refund, block.timestamp);
        }

        emit PaymentReceived(paymentId, loanId, msg.sender, actualPayment, block.timestamp);

        // Check if loan is fully repaid
        if (totalPaidByLoan[loanId] >= loan.approvedAmount) {
            emit FullyRepaid(loanId, totalPaidByLoan[loanId], block.timestamp);
        }

        return paymentId;
    }

    /**
     * @notice Pay on behalf of another borrower (officer/admin)
     * @param loanId The loan identifier
     * @param amount Amount to pay
     * @param onBehalfOf Address of the borrower
     * @return paymentId The generated payment ID
     */
    function repayOnBehalf(bytes32 loanId, uint256 amount, address onBehalfOf) 
        external 
        nonReentrant 
        whenNotPaused 
        onlyRole(LOAN_OFFICER_ROLE)
        returns (bytes32 paymentId)
    {
        if (amount == 0) revert ZeroAmount();

        // Get loan details
        ILoanCore.Loan memory loan = loanCore.getLoan(loanId);
        
        // Verify loan is active
        if (loan.status != ILoanCore.LoanStatus.Disbursed && 
            loan.status != ILoanCore.LoanStatus.Active) {
            revert InvalidLoanStatus();
        }

        // Verify the onBehalfOf is the actual borrower
        if (loan.borrower != onBehalfOf) {
            revert NotBorrower();
        }

        // Generate unique payment ID
        _paymentNonce++;
        paymentId = keccak256(abi.encodePacked(
            loanId,
            onBehalfOf,
            amount,
            block.timestamp,
            _paymentNonce
        ));

        // Update state
        uint256 remainingBalance = _getRemainingBalance(loanId, loan.approvedAmount);
        bool isPartial = amount < remainingBalance;

        PaymentRecord memory record = PaymentRecord({
            paymentId: paymentId,
            loanId: loanId,
            payer: onBehalfOf,
            amount: amount,
            timestamp: block.timestamp,
            isPartial: isPartial
        });

        loanPayments[loanId].push(record);
        totalPaidByLoan[loanId] += amount;
        usedPaymentIds[paymentId] = true;
        totalPaymentsReceived++;
        totalAmountReceived += amount;

        // Transfer from officer/admin to treasury
        loanToken.safeTransferFrom(msg.sender, treasury, amount);

        emit PaymentReceived(paymentId, loanId, onBehalfOf, amount, block.timestamp);

        // Check if loan is fully repaid
        if (totalPaidByLoan[loanId] >= loan.approvedAmount) {
            emit FullyRepaid(loanId, totalPaidByLoan[loanId], block.timestamp);
        }

        return paymentId;
    }

    // ============ View Functions ============

    /**
     * @notice Get all payments for a loan
     * @param loanId The loan identifier
     * @return Array of payment records
     */
    function getPayments(bytes32 loanId) 
        external 
        view 
        returns (PaymentRecord[] memory) 
    {
        return loanPayments[loanId];
    }

    /**
     * @notice Get payment count for a loan
     * @param loanId The loan identifier
     * @return Number of payments made
     */
    function getPaymentCount(bytes32 loanId) external view returns (uint256) {
        return loanPayments[loanId].length;
    }

    /**
     * @notice Get remaining balance for a loan
     * @param loanId The loan identifier
     * @return Remaining amount to be paid
     */
    function getRemainingBalance(bytes32 loanId) external view returns (uint256) {
        ILoanCore.Loan memory loan = loanCore.getLoan(loanId);
        return _getRemainingBalance(loanId, loan.approvedAmount);
    }

    /**
     * @notice Check if a loan is fully repaid
     * @param loanId The loan identifier
     * @return True if fully repaid
     */
    function isFullyRepaid(bytes32 loanId) external view returns (bool) {
        ILoanCore.Loan memory loan = loanCore.getLoan(loanId);
        return totalPaidByLoan[loanId] >= loan.approvedAmount;
    }

    /**
     * @notice Get contract statistics
     */
    function getStats() external view returns (
        uint256 _totalPayments,
        uint256 _totalAmount,
        uint256 _treasuryBalance
    ) {
        return (
            totalPaymentsReceived,
            totalAmountReceived,
            loanToken.balanceOf(treasury)
        );
    }

    // ============ Internal Functions ============

    function _getRemainingBalance(bytes32 loanId, uint256 approvedAmount) 
        internal 
        view 
        returns (uint256) 
    {
        uint256 paid = totalPaidByLoan[loanId];
        return paid >= approvedAmount ? 0 : approvedAmount - paid;
    }

    // ============ Admin Functions ============

    function setTreasury(address newTreasury) external onlyRole(ADMIN_ROLE) {
        if (newTreasury == address(0)) revert ZeroAddress();
        treasury = newTreasury;
    }

    function pause() external onlyRole(ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(ADMIN_ROLE) {
        _unpause();
    }

    // ============ Upgrade Authorization ============

    function _authorizeUpgrade(address newImplementation) 
        internal 
        override 
        onlyRole(UPGRADER_ROLE) 
    {}
}
