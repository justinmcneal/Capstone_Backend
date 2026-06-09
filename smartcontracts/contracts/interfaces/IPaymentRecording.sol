// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IPaymentRecording {
    function recordPayment(bytes32 loanId, uint16 installmentNumber, uint256 amount, uint8 paymentMethod, bytes32 referenceHash) external;
    function markOverdue(bytes32 loanId, uint16 installmentNumber) external;
}
