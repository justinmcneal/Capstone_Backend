// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IDisbursementExecution {
    function initiateDisbursement(bytes32 loanId, uint256 amount, uint8 method) external returns (bytes32);
    function completeDisbursement(bytes32 disbursementId, bytes32 referenceHash) external;
}
