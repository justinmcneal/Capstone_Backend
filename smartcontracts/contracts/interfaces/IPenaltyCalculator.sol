// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title IPenaltyCalculator
 * @notice Interface for the penalty calculator contract
 */
interface IPenaltyCalculator {
    struct PenaltyConfig {
        uint256 gracePeriodDays;
        uint16 lateFeePercentBps;
        uint16 dailyPenaltyBps;
        uint256 maxPenaltyPercent;
        bool compoundPenalty;
    }

    struct PenaltyRecord {
        bytes32 loanId;
        uint16 installmentNumber;
        uint256 originalAmount;
        uint256 penaltyAmount;
        uint256 daysOverdue;
        uint256 calculatedAt;
        bool waived;
        address waivedBy;
        bytes32 waiveReasonHash;
    }

    function calculatePenalty(
        bytes32 loanId,
        uint16 installmentNumber,
        uint256 originalAmount,
        uint256 dueDate
    ) external view returns (uint256 penaltyAmount, uint256 daysOverdue);

    function recordPenalty(
        bytes32 loanId,
        uint16 installmentNumber,
        uint256 penaltyAmount
    ) external returns (bool);

    function waivePenalty(
        bytes32 loanId,
        uint16 installmentNumber,
        bytes32 reasonHash
    ) external returns (bool);

    function getConfig() external view returns (PenaltyConfig memory);
}
