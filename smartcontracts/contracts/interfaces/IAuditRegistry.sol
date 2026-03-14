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
        bytes32 resourceId;
        bytes32 resourceType;       // was string — bytes32 saves ~20K gas
        bytes32 detailsHash;
        bytes32 previousStateHash;
        bytes32 newStateHash;
        AuditAction action;         // uint8, packed with actor
        address actor;              // 20 bytes — shares slot with action
        uint48 timestamp;           // sufficient until year 8M
        uint48 blockNumber;         // shares slot with timestamp
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
        bytes32 resourceType,
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
