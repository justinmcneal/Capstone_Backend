// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import "./interfaces/IAuditRegistry.sol";

/**
 * @title AuditRegistry
 * @notice Immutable audit log for all loan system transactions
 * @dev Records state transitions and provides verification capabilities
 */
contract AuditRegistry is 
    Initializable,
    AccessControlUpgradeable,
    UUPSUpgradeable,
    IAuditRegistry 
{
    // ============ Constants ============
    uint256 public constant VERSION = 1;
    
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant LOGGER_ROLE = keccak256("LOGGER_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ State Variables ============
    // Entry storage
    mapping(bytes32 => AuditEntry) public entries;
    
    // Indexes
    mapping(bytes32 => bytes32[]) public resourceEntries;     // resourceId => entryIds[]
    mapping(address => bytes32[]) public actorEntries;        // actor => entryIds[]
    mapping(bytes32 => bytes32) public latestResourceState;   // resourceId => latest state hash
    
    // Counters
    uint256 public totalEntries;
    uint256 private _entryNonce;

    // ============ Initializer ============
    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /**
     * @notice Initialize the contract
     */
    function initialize(address admin) public initializer {
        require(admin != address(0), "Zero address");

        __AccessControl_init();
        __UUPSUpgradeable_init();

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        _grantRole(LOGGER_ROLE, admin);
        _grantRole(UPGRADER_ROLE, admin);
    }

    /**
     * @notice Grant logger role to a contract
     */
    function grantLoggerRole(address contractAddress) external onlyRole(ADMIN_ROLE) {
        _grantRole(LOGGER_ROLE, contractAddress);
    }

    // ============ Logging Functions ============

    /**
     * @notice Log an audit entry
     * @param resourceId ID of the resource being acted upon
     * @param resourceType Type of resource (loan, payment, etc.)
     * @param action Action performed
     * @param detailsHash Hash of detailed off-chain data
     * @param previousStateHash Hash of previous state
     * @param newStateHash Hash of new state
     */
    function log(
        bytes32 resourceId,
        string calldata resourceType,
        AuditAction action,
        bytes32 detailsHash,
        bytes32 previousStateHash,
        bytes32 newStateHash
    ) external override onlyRole(LOGGER_ROLE) returns (bytes32 entryId) {
        require(resourceId != bytes32(0), "AuditRegistry: empty resource ID");
        require(bytes(resourceType).length > 0, "AuditRegistry: empty resource type");

        // Generate entry ID
        _entryNonce++;
        entryId = keccak256(abi.encodePacked(
            resourceId,
            action,
            block.timestamp,
            _entryNonce
        ));

        // Create entry
        AuditEntry storage entry = entries[entryId];
        entry.entryId = entryId;
        entry.resourceId = resourceId;
        entry.resourceType = resourceType;
        entry.action = action;
        entry.actor = msg.sender;
        entry.detailsHash = detailsHash;
        entry.previousStateHash = previousStateHash;
        entry.newStateHash = newStateHash;
        entry.timestamp = block.timestamp;
        entry.blockNumber = block.number;

        // Update indexes
        resourceEntries[resourceId].push(entryId);
        actorEntries[msg.sender].push(entryId);
        latestResourceState[resourceId] = newStateHash;

        totalEntries++;

        emit AuditLogged(entryId, resourceId, action, msg.sender, block.timestamp);

        return entryId;
    }

    /**
     * @notice Log multiple entries in batch (gas efficient for bulk operations)
     */
    function logBatch(
        bytes32[] calldata resourceIds,
        string[] calldata resourceTypes,
        AuditAction[] calldata actions,
        bytes32[] calldata detailsHashes,
        bytes32[] calldata previousStateHashes,
        bytes32[] calldata newStateHashes
    ) external onlyRole(LOGGER_ROLE) returns (bytes32[] memory entryIds) {
        require(
            resourceIds.length == resourceTypes.length &&
            resourceIds.length == actions.length &&
            resourceIds.length == detailsHashes.length &&
            resourceIds.length == previousStateHashes.length &&
            resourceIds.length == newStateHashes.length,
            "AuditRegistry: array length mismatch"
        );
        require(resourceIds.length <= 50, "AuditRegistry: batch too large");

        entryIds = new bytes32[](resourceIds.length);

        for (uint256 i = 0; i < resourceIds.length; i++) {
            _entryNonce++;
            bytes32 entryId = keccak256(abi.encodePacked(
                resourceIds[i],
                actions[i],
                block.timestamp,
                _entryNonce
            ));

            AuditEntry storage entry = entries[entryId];
            entry.entryId = entryId;
            entry.resourceId = resourceIds[i];
            entry.resourceType = resourceTypes[i];
            entry.action = actions[i];
            entry.actor = msg.sender;
            entry.detailsHash = detailsHashes[i];
            entry.previousStateHash = previousStateHashes[i];
            entry.newStateHash = newStateHashes[i];
            entry.timestamp = block.timestamp;
            entry.blockNumber = block.number;

            resourceEntries[resourceIds[i]].push(entryId);
            actorEntries[msg.sender].push(entryId);
            latestResourceState[resourceIds[i]] = newStateHashes[i];

            entryIds[i] = entryId;
            totalEntries++;

            emit AuditLogged(entryId, resourceIds[i], actions[i], msg.sender, block.timestamp);
        }

        return entryIds;
    }

    // ============ View Functions ============

    /**
     * @notice Get audit entry by ID
     */
    function getEntry(bytes32 entryId) external view override returns (AuditEntry memory) {
        return entries[entryId];
    }

    /**
     * @notice Get all entries for a resource
     */
    function getEntriesByResource(bytes32 resourceId) external view override returns (bytes32[] memory) {
        return resourceEntries[resourceId];
    }

    /**
     * @notice Get entries by actor with limit
     */
    function getEntriesByActor(address actor, uint256 limit) external view override returns (bytes32[] memory) {
        bytes32[] storage allEntries = actorEntries[actor];
        uint256 count = allEntries.length;
        
        if (limit == 0 || limit > count) {
            limit = count;
        }

        bytes32[] memory result = new bytes32[](limit);
        
        // Return most recent entries first
        for (uint256 i = 0; i < limit; i++) {
            result[i] = allEntries[count - 1 - i];
        }

        return result;
    }

    /**
     * @notice Verify current state of a resource
     */
    function verifyStateTransition(
        bytes32 resourceId,
        bytes32 expectedStateHash
    ) external view override returns (bool) {
        return latestResourceState[resourceId] == expectedStateHash;
    }

    /**
     * @notice Get entry count for a resource
     */
    function getResourceEntryCount(bytes32 resourceId) external view returns (uint256) {
        return resourceEntries[resourceId].length;
    }

    /**
     * @notice Get latest state hash for a resource
     */
    function getLatestState(bytes32 resourceId) external view returns (bytes32) {
        return latestResourceState[resourceId];
    }

    /**
     * @notice Get full audit trail for a resource (with entries)
     */
    function getFullAuditTrail(bytes32 resourceId) external view returns (AuditEntry[] memory) {
        bytes32[] storage entryIds = resourceEntries[resourceId];
        AuditEntry[] memory trail = new AuditEntry[](entryIds.length);
        
        for (uint256 i = 0; i < entryIds.length; i++) {
            trail[i] = entries[entryIds[i]];
        }

        return trail;
    }

    /**
     * @notice Verify an audit trail is valid (each state follows from previous)
     */
    function verifyAuditTrail(bytes32 resourceId) external view returns (bool isValid, uint256 brokenAt) {
        bytes32[] storage entryIds = resourceEntries[resourceId];
        
        if (entryIds.length == 0) {
            return (true, 0);
        }

        for (uint256 i = 1; i < entryIds.length; i++) {
            AuditEntry storage current = entries[entryIds[i]];
            AuditEntry storage previous = entries[entryIds[i - 1]];
            
            // Current's previous state should match previous entry's new state
            if (current.previousStateHash != previous.newStateHash) {
                return (false, i);
            }
        }

        return (true, 0);
    }

    // ============ Upgrade Functions ============

    function _authorizeUpgrade(address newImplementation) internal override onlyRole(UPGRADER_ROLE) {}
}
