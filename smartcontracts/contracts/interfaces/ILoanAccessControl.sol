// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title ILoanAccessControl
 * @notice Interface for the central access control contract
 */
interface ILoanAccessControl {
    function isActiveOfficer(address officer) external view returns (bool);
    function isBorrower(address account) external view returns (bool);
    function getOfficerInfo(address officer) external view returns (
        bytes32 employeeIdHash,
        bool isActive,
        uint256 registeredAt
    );
    function getBorrowerInfo(address borrower) external view returns (
        bytes32 customerIdHash,
        uint256 registeredAt
    );
}
