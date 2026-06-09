// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IRepaymentSchedule {
    function createSchedule(bytes32 loanId, address borrower, uint256 principal, uint16 interestRateBps, uint16 termMonths, uint256 startDate) external;
    function getSchedule(bytes32 loanId) external view returns (bytes32[] memory);
    function getInstallment(bytes32 loanId, uint16 installmentNumber) external view returns (bytes32);
}
