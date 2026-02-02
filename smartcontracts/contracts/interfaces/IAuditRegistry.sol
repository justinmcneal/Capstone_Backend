// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title IAuditRegistry
 * @notice Interface for the audit registry contract
 */
interface IAuditRegistry {
    enum AuditAction {
        LoanCreated,
        LoanSubmitted,
        LoanAssigned,
        LoanApproved,
        LoanRejected,
        LoanDisbursed,
        PaymentRecorded,
        PenaltyApplied,
        PenaltyWaived,
        DocumentVerified,
        ConsentRecorded,
        SystemConfigChanged
    }

    struct AuditEntry {
        bytes32 entryId;
        bytes32 resourceId;
        string resourceType;
        AuditAction action;
        address actor;
        bytes32 detailsHash;
        bytes32 previousStateHash;
        bytes32 newStateHash;
        uint256 timestamp;
        uint256 blockNumber;
    }

    event AuditLogged(
        bytes32 indexed entryId,
        bytes32 indexed resourceId,
        AuditAction indexed action,
        address actor,
        uint256 timestamp
    );

    function log(
        bytes32 resourceId,
        string calldata resourceType,
        AuditAction action,
        bytes32 detailsHash,
        bytes32 previousStateHash,
        bytes32 newStateHash
    ) external returns (bytes32 entryId);

    function getEntry(bytes32 entryId) external view returns (AuditEntry memory);
    function getEntriesByResource(bytes32 resourceId) external view returns (bytes32[] memory);
    function getEntriesByActor(address actor, uint256 limit) external view returns (bytes32[] memory);
    function verifyStateTransition(bytes32 resourceId, bytes32 expectedStateHash) external view returns (bool);
}
