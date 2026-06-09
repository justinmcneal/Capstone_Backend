// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface ILoanApproval {
    function approveLoan(bytes32 loanId, uint256 approvedAmount, bytes32 notesHash) external;
    function rejectLoan(bytes32 loanId, bytes32 rejectionReasonHash, bytes32 notesHash) external;
}
