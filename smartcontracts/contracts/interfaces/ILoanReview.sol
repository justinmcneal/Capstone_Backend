// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface ILoanReview {
    function assignOfficer(bytes32 loanId, address officer) external;
    function getAssignedOfficer(bytes32 loanId) external view returns (address);
}
