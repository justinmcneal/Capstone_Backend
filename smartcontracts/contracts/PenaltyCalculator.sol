// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import "./interfaces/IPenaltyCalculator.sol";

/**
 * @title PenaltyCalculator
 * @notice Calculates late fees and penalties for overdue loan installments
 * @dev Configurable penalty rules with grace period support
 */
contract PenaltyCalculator is 
    Initializable,
    AccessControlUpgradeable,
    UUPSUpgradeable,
    IPenaltyCalculator 
{
    // ============ Constants ============
    uint256 public constant VERSION = 1;
    uint256 public constant SECONDS_PER_DAY = 86400;
    uint256 public constant MAX_BPS = 10000;
    
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant LOAN_OFFICER_ROLE = keccak256("LOAN_OFFICER_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ State Variables ============
    PenaltyConfig public config;

    // Penalty records
    mapping(bytes32 => mapping(uint16 => PenaltyRecord)) public penaltyRecords;

    // ============ Events ============
    event PenaltyCalculated(
        bytes32 indexed loanId,
        uint16 indexed installmentNumber,
        uint256 penaltyAmount,
        uint256 daysOverdue,
        uint256 timestamp
    );

    event PenaltyWaived(
        bytes32 indexed loanId,
        uint16 indexed installmentNumber,
        address indexed waivedBy,
        uint256 amount,
        bytes32 reasonHash,
        uint256 timestamp
    );

    event PenaltyConfigUpdated(
        uint256 gracePeriodDays,
        uint16 lateFeePercentBps,
        uint16 dailyPenaltyBps,
        uint256 maxPenaltyPercent,
        uint256 timestamp
    );

    // ============ Initializer ============
    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /**
     * @notice Initialize the contract with default penalty config
     */
    function initialize(address admin) public initializer {
        require(admin != address(0), "Zero address");

        __AccessControl_init();
        __UUPSUpgradeable_init();

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        _grantRole(UPGRADER_ROLE, admin);

        // Default configuration
        config = PenaltyConfig({
            gracePeriodDays: 3,           // 3 days grace period
            lateFeePercentBps: 500,       // 5% one-time late fee
            dailyPenaltyBps: 10,          // 0.1% daily penalty
            maxPenaltyPercent: 25,        // Max 25% of original amount
            compoundPenalty: false        // Simple interest
        });
    }

    // ============ Penalty Calculation ============

    /**
     * @notice Calculate penalty for an overdue installment
     * @param loanId Loan identifier
     * @param installmentNumber Installment number
     * @param originalAmount Original installment amount
     * @param dueDate Due date timestamp
     * @return penaltyAmount Total penalty amount
     * @return daysOverdue Number of days overdue
     */
    function calculatePenalty(
        bytes32 loanId,
        uint16 installmentNumber,
        uint256 originalAmount,
        uint256 dueDate
    ) external view override returns (uint256 penaltyAmount, uint256 daysOverdue) {
        // Check if still in grace period
        uint256 graceEnd = dueDate + (config.gracePeriodDays * SECONDS_PER_DAY);
        
        if (block.timestamp <= graceEnd) {
            return (0, 0);
        }

        // Calculate days overdue (excluding grace period)
        daysOverdue = (block.timestamp - graceEnd) / SECONDS_PER_DAY;
        if (daysOverdue == 0) {
            daysOverdue = 1; // At least 1 day if past grace period
        }

        // Calculate one-time late fee
        uint256 lateFee = (originalAmount * config.lateFeePercentBps) / MAX_BPS;

        // Calculate daily penalty
        uint256 dailyPenalty;
        if (config.compoundPenalty) {
            // Compound penalty calculation
            uint256 base = originalAmount;
            for (uint256 i = 0; i < daysOverdue && i < 365; i++) {
                base += (base * config.dailyPenaltyBps) / MAX_BPS;
            }
            dailyPenalty = base - originalAmount;
        } else {
            // Simple penalty calculation
            dailyPenalty = (originalAmount * config.dailyPenaltyBps * daysOverdue) / MAX_BPS;
        }

        penaltyAmount = lateFee + dailyPenalty;

        // Apply maximum cap
        uint256 maxPenalty = (originalAmount * config.maxPenaltyPercent) / 100;
        if (penaltyAmount > maxPenalty) {
            penaltyAmount = maxPenalty;
        }

        return (penaltyAmount, daysOverdue);
    }

    /**
     * @notice Record a penalty (called by Repayment contract)
     */
    function recordPenalty(
        bytes32 loanId,
        uint16 installmentNumber,
        uint256 penaltyAmount
    ) external override returns (bool) {
        require(
            hasRole(ADMIN_ROLE, msg.sender) || 
            msg.sender == address(this),
            "PenaltyCalculator: not authorized"
        );

        PenaltyRecord storage record = penaltyRecords[loanId][installmentNumber];
        record.loanId = loanId;
        record.installmentNumber = installmentNumber;
        record.penaltyAmount = penaltyAmount;
        record.calculatedAt = block.timestamp;

        emit PenaltyCalculated(
            loanId,
            installmentNumber,
            penaltyAmount,
            0, // daysOverdue can be recalculated
            block.timestamp
        );

        return true;
    }

    /**
     * @notice Waive a penalty for an installment
     */
    function waivePenalty(
        bytes32 loanId,
        uint16 installmentNumber,
        bytes32 reasonHash
    ) external override returns (bool) {
        require(
            hasRole(ADMIN_ROLE, msg.sender) || hasRole(LOAN_OFFICER_ROLE, msg.sender),
            "PenaltyCalculator: not authorized"
        );
        require(reasonHash != bytes32(0), "PenaltyCalculator: reason required");

        PenaltyRecord storage record = penaltyRecords[loanId][installmentNumber];
        require(!record.waived, "PenaltyCalculator: already waived");
        
        uint256 waivedAmount = record.penaltyAmount;
        record.waived = true;
        record.waivedBy = msg.sender;
        record.waiveReasonHash = reasonHash;

        emit PenaltyWaived(
            loanId,
            installmentNumber,
            msg.sender,
            waivedAmount,
            reasonHash,
            block.timestamp
        );

        return true;
    }

    // ============ Configuration ============

    /**
     * @notice Update penalty configuration
     */
    function updateConfig(
        uint256 gracePeriodDays,
        uint16 lateFeePercentBps,
        uint16 dailyPenaltyBps,
        uint256 maxPenaltyPercent,
        bool compoundPenalty
    ) external onlyRole(ADMIN_ROLE) returns (bool) {
        require(gracePeriodDays <= 30, "PenaltyCalculator: grace period too long");
        require(lateFeePercentBps <= 2000, "PenaltyCalculator: late fee too high"); // Max 20%
        require(dailyPenaltyBps <= 100, "PenaltyCalculator: daily penalty too high"); // Max 1%
        require(maxPenaltyPercent <= 50, "PenaltyCalculator: max penalty too high"); // Max 50%

        config = PenaltyConfig({
            gracePeriodDays: gracePeriodDays,
            lateFeePercentBps: lateFeePercentBps,
            dailyPenaltyBps: dailyPenaltyBps,
            maxPenaltyPercent: maxPenaltyPercent,
            compoundPenalty: compoundPenalty
        });

        emit PenaltyConfigUpdated(
            gracePeriodDays,
            lateFeePercentBps,
            dailyPenaltyBps,
            maxPenaltyPercent,
            block.timestamp
        );

        return true;
    }

    // ============ View Functions ============

    /**
     * @notice Get current penalty configuration
     */
    function getConfig() external view override returns (PenaltyConfig memory) {
        return config;
    }

    /**
     * @notice Get penalty record for an installment
     */
    function getPenaltyRecord(
        bytes32 loanId,
        uint16 installmentNumber
    ) external view returns (PenaltyRecord memory) {
        return penaltyRecords[loanId][installmentNumber];
    }

    /**
     * @notice Check if penalty has been waived
     */
    function isPenaltyWaived(
        bytes32 loanId,
        uint16 installmentNumber
    ) external view returns (bool) {
        return penaltyRecords[loanId][installmentNumber].waived;
    }

    // ============ Upgrade Functions ============

    function _authorizeUpgrade(address newImplementation) internal override onlyRole(UPGRADER_ROLE) {}
}
