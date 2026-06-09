// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IDisbursementMethod {
    enum Method { BankTransfer, Cash, GCash, Other }
    function setPreferredMethod(bytes32 loanId, uint8 method) external;
    function getPreferredMethod(bytes32 loanId) external view returns (uint8);
}
