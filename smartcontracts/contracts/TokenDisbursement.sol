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
 * @title TokenDisbursement
 * @notice Handles actual ERC20 token transfers for loan disbursements
 * @dev This contract manages real token movements, unlike Disbursement.sol which only tracks records
 * 
 * Flow:
 * 1. Treasury deposits tokens to this contract
 * 2. When loan is approved, tokens are reserved
 * 3. On disbursement completion, tokens are transferred to borrower
 * 4. On repayment, borrower transfers tokens back to treasury
 */
contract TokenDisbursement is 
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable 
{
    using SafeERC20 for IERC20;

    // ============ Type Definitions ============
    enum DisbursementStatus {
        None,            // 0 - Not initiated
        Reserved,        // 1 - Funds reserved for this loan
        Disbursed,       // 2 - Funds sent to borrower
        Returned,        // 3 - Funds returned (loan cancelled/rejected)
        Defaulted        // 4 - Loan defaulted, funds lost
    }

    struct TokenDisbursementRecord {
        bytes32 loanId;
        address borrower;
        uint256 amount;
        DisbursementStatus status;
        uint256 reservedAt;
        uint256 disbursedAt;
        uint256 returnedAt;
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

    // Disbursement storage
    mapping(bytes32 => TokenDisbursementRecord) public disbursements;
    
    // Counters
    uint256 public totalReserved;
    uint256 public totalDisbursed;
    uint256 public totalReturned;

    // ============ Events ============
    event FundsReserved(
        bytes32 indexed loanId,
        address indexed borrower,
        uint256 amount,
        uint256 timestamp
    );

    event FundsDisbursed(
        bytes32 indexed loanId,
        address indexed borrower,
        uint256 amount,
        address indexed processedBy,
        uint256 timestamp
    );

    event FundsReturned(
        bytes32 indexed loanId,
        uint256 amount,
        bytes32 reasonHash,
        uint256 timestamp
    );

    event TreasuryUpdated(address indexed oldTreasury, address indexed newTreasury);
    event TokenUpdated(address indexed oldToken, address indexed newToken);

    // ============ Errors ============
    error InvalidLoanStatus();
    error InsufficientBalance();
    error AlreadyReserved();
    error NotReserved();
    error AlreadyDisbursed();
    error ZeroAmount();
    error ZeroAddress();

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
     * @notice Reserve funds for an approved loan
     * @dev Called after loan approval to lock funds
     * @param loanId The loan identifier
     */
    function reserveFunds(bytes32 loanId) 
        external 
        nonReentrant 
        whenNotPaused 
        onlyRole(SYSTEM_ROLE) 
    {
        // Get loan details
        ILoanCore.Loan memory loan = loanCore.getLoan(loanId);
        
        // Verify loan is approved
        if (loan.status != ILoanCore.LoanStatus.Approved) {
            revert InvalidLoanStatus();
        }

        TokenDisbursementRecord storage record = disbursements[loanId];
        
        if (record.status != DisbursementStatus.None) {
            revert AlreadyReserved();
        }

        uint256 amount = loan.approvedAmount;
        if (amount == 0) {
            revert ZeroAmount();
        }

        // Check contract has sufficient balance
        if (loanToken.balanceOf(address(this)) < totalReserved + amount) {
            revert InsufficientBalance();
        }

        // Create reservation record
        record.loanId = loanId;
        record.borrower = loan.borrower;
        record.amount = amount;
        record.status = DisbursementStatus.Reserved;
        record.reservedAt = block.timestamp;

        totalReserved += amount;

        emit FundsReserved(loanId, loan.borrower, amount, block.timestamp);
    }

    /**
     * @notice Disburse reserved funds to borrower
     * @dev Transfers tokens from contract to borrower
     * @param loanId The loan identifier
     */
    function disburseFunds(bytes32 loanId) 
        external 
        nonReentrant 
        whenNotPaused 
        onlyRole(LOAN_OFFICER_ROLE) 
    {
        TokenDisbursementRecord storage record = disbursements[loanId];

        if (record.status != DisbursementStatus.Reserved) {
            revert NotReserved();
        }

        // Update state BEFORE transfer (CEI pattern)
        record.status = DisbursementStatus.Disbursed;
        record.disbursedAt = block.timestamp;

        totalReserved -= record.amount;
        totalDisbursed += record.amount;

        // Transfer tokens to borrower
        loanToken.safeTransfer(record.borrower, record.amount);

        emit FundsDisbursed(
            loanId, 
            record.borrower, 
            record.amount, 
            msg.sender, 
            block.timestamp
        );
    }

    /**
     * @notice Return reserved funds to treasury
     * @dev Used when loan is cancelled or rejected after reservation
     * @param loanId The loan identifier
     * @param reasonHash Hash of the reason for return
     */
    function returnFunds(bytes32 loanId, bytes32 reasonHash) 
        external 
        nonReentrant 
        whenNotPaused 
        onlyRole(ADMIN_ROLE) 
    {
        TokenDisbursementRecord storage record = disbursements[loanId];

        if (record.status != DisbursementStatus.Reserved) {
            revert NotReserved();
        }

        uint256 amount = record.amount;

        // Update state BEFORE transfer
        record.status = DisbursementStatus.Returned;
        record.returnedAt = block.timestamp;

        totalReserved -= amount;
        totalReturned += amount;

        // Transfer back to treasury
        loanToken.safeTransfer(treasury, amount);

        emit FundsReturned(loanId, amount, reasonHash, block.timestamp);
    }

    // ============ Treasury Functions ============

    /**
     * @notice Deposit tokens from treasury
     * @dev Treasury must approve this contract first
     * @param amount Amount to deposit
     */
    function depositFromTreasury(uint256 amount) 
        external 
        nonReentrant 
        onlyRole(ADMIN_ROLE) 
    {
        if (amount == 0) revert ZeroAmount();
        loanToken.safeTransferFrom(treasury, address(this), amount);
    }

    /**
     * @notice Withdraw excess tokens to treasury
     * @dev Can only withdraw unreserved funds
     * @param amount Amount to withdraw
     */
    function withdrawToTreasury(uint256 amount) 
        external 
        nonReentrant 
        onlyRole(ADMIN_ROLE) 
    {
        if (amount == 0) revert ZeroAmount();
        
        uint256 available = loanToken.balanceOf(address(this)) - totalReserved;
        require(amount <= available, "Exceeds available balance");
        
        loanToken.safeTransfer(treasury, amount);
    }

    /**
     * @notice Update treasury address
     * @param newTreasury New treasury address
     */
    function setTreasury(address newTreasury) external onlyRole(ADMIN_ROLE) {
        if (newTreasury == address(0)) revert ZeroAddress();
        
        address oldTreasury = treasury;
        treasury = newTreasury;
        
        emit TreasuryUpdated(oldTreasury, newTreasury);
    }

    /**
     * @notice Update loan token (for migration)
     * @param newToken New token address
     */
    function setLoanToken(address newToken) external onlyRole(ADMIN_ROLE) {
        if (newToken == address(0)) revert ZeroAddress();
        require(totalReserved == 0, "Cannot change with reserved funds");
        
        address oldToken = address(loanToken);
        loanToken = IERC20(newToken);
        
        emit TokenUpdated(oldToken, newToken);
    }

    // ============ View Functions ============

    /**
     * @notice Get disbursement record for a loan
     * @param loanId The loan identifier
     * @return The disbursement record
     */
    function getDisbursement(bytes32 loanId) 
        external 
        view 
        returns (TokenDisbursementRecord memory) 
    {
        return disbursements[loanId];
    }

    /**
     * @notice Get available balance for new reservations
     * @return Available token balance
     */
    function getAvailableBalance() external view returns (uint256) {
        uint256 balance = loanToken.balanceOf(address(this));
        return balance > totalReserved ? balance - totalReserved : 0;
    }

    /**
     * @notice Get contract statistics
     */
    function getStats() external view returns (
        uint256 _totalReserved,
        uint256 _totalDisbursed,
        uint256 _totalReturned,
        uint256 _contractBalance
    ) {
        return (
            totalReserved,
            totalDisbursed,
            totalReturned,
            loanToken.balanceOf(address(this))
        );
    }

    // ============ Admin Functions ============

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
