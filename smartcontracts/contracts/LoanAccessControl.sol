// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

/**
 * @title LoanAccessControl
 * @notice Central access control for the MSME Loan system
 * @dev Uses OpenZeppelin's AccessControl with UUPS upgrade pattern
 */
contract LoanAccessControl is 
    Initializable, 
    AccessControlUpgradeable, 
    PausableUpgradeable,
    ReentrancyGuardUpgradeable,
    UUPSUpgradeable 
{
    // ============ Role Definitions ============
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant LOAN_OFFICER_ROLE = keccak256("LOAN_OFFICER_ROLE");
    bytes32 public constant BORROWER_ROLE = keccak256("BORROWER_ROLE");
    bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");
    bytes32 public constant SYSTEM_ROLE = keccak256("SYSTEM_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");

    // ============ State Variables ============
    uint256 public constant VERSION = 1;
    
    // Officer tracking
    mapping(address => bytes32) public officerEmployeeIds;
    mapping(address => bool) public activeOfficers;
    mapping(address => uint256) public officerRegisteredAt;
    
    // Borrower tracking
    mapping(address => bytes32) public borrowerCustomerIds;
    mapping(address => uint256) public borrowerRegisteredAt;
    
    // Emergency state
    string public pauseReason;
    uint256 public pausedAt;
    address public pausedBy;

    // ============ Events ============
    event OfficerRegistered(
        address indexed officer,
        bytes32 indexed employeeIdHash,
        address indexed registeredBy,
        uint256 timestamp
    );

    event OfficerDeactivated(
        address indexed officer,
        address indexed deactivatedBy,
        uint256 timestamp
    );

    event OfficerReactivated(
        address indexed officer,
        address indexed reactivatedBy,
        uint256 timestamp
    );

    event BorrowerRegistered(
        address indexed borrower,
        bytes32 indexed customerIdHash,
        uint256 timestamp
    );

    event EmergencyPaused(
        address indexed pausedBy,
        string reason,
        uint256 timestamp
    );

    event Unpaused(
        address indexed unpausedBy,
        uint256 timestamp
    );

    // ============ Modifiers ============
    modifier onlyActiveOfficer() {
        require(
            activeOfficers[msg.sender] && hasRole(LOAN_OFFICER_ROLE, msg.sender),
            "LoanAccessControl: caller is not an active officer"
        );
        _;
    }

    modifier onlyBorrower() {
        require(
            hasRole(BORROWER_ROLE, msg.sender),
            "LoanAccessControl: caller is not a borrower"
        );
        _;
    }

    // ============ Initializer ============
    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /**
     * @notice Initialize the contract
     * @param admin Address of the initial admin
     */
    function initialize(address admin) public initializer {
        __AccessControl_init();
        __Pausable_init();
        __ReentrancyGuard_init();
        __UUPSUpgradeable_init();

        // Set up role hierarchy
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        _grantRole(UPGRADER_ROLE, admin);
        _grantRole(PAUSER_ROLE, admin);

        // Admin can grant all roles
        _setRoleAdmin(LOAN_OFFICER_ROLE, ADMIN_ROLE);
        _setRoleAdmin(BORROWER_ROLE, SYSTEM_ROLE);
        _setRoleAdmin(ORACLE_ROLE, ADMIN_ROLE);
        _setRoleAdmin(SYSTEM_ROLE, ADMIN_ROLE);
    }

    // ============ Officer Management ============
    
    /**
     * @notice Register a new loan officer
     * @param officer Address of the officer
     * @param employeeIdHash Hash of the employee ID
     */
    function registerOfficer(
        address officer, 
        bytes32 employeeIdHash
    ) external onlyRole(ADMIN_ROLE) whenNotPaused nonReentrant returns (bool) {
        require(officer != address(0), "LoanAccessControl: zero address");
        require(employeeIdHash != bytes32(0), "LoanAccessControl: empty employee ID");
        require(!hasRole(LOAN_OFFICER_ROLE, officer), "LoanAccessControl: already registered");

        _grantRole(LOAN_OFFICER_ROLE, officer);
        officerEmployeeIds[officer] = employeeIdHash;
        activeOfficers[officer] = true;
        officerRegisteredAt[officer] = block.timestamp;

        emit OfficerRegistered(officer, employeeIdHash, msg.sender, block.timestamp);
        return true;
    }

    /**
     * @notice Deactivate a loan officer (soft delete)
     * @param officer Address of the officer to deactivate
     */
    function deactivateOfficer(address officer) external onlyRole(ADMIN_ROLE) nonReentrant returns (bool) {
        require(hasRole(LOAN_OFFICER_ROLE, officer), "LoanAccessControl: not an officer");
        require(activeOfficers[officer], "LoanAccessControl: already inactive");

        activeOfficers[officer] = false;

        emit OfficerDeactivated(officer, msg.sender, block.timestamp);
        return true;
    }

    /**
     * @notice Reactivate a loan officer
     * @param officer Address of the officer to reactivate
     */
    function reactivateOfficer(address officer) external onlyRole(ADMIN_ROLE) nonReentrant returns (bool) {
        require(hasRole(LOAN_OFFICER_ROLE, officer), "LoanAccessControl: not an officer");
        require(!activeOfficers[officer], "LoanAccessControl: already active");

        activeOfficers[officer] = true;

        emit OfficerReactivated(officer, msg.sender, block.timestamp);
        return true;
    }

    // ============ Borrower Management ============

    /**
     * @notice Register a new borrower
     * @param borrower Address of the borrower
     * @param customerIdHash Hash of the customer ID
     */
    function registerBorrower(
        address borrower, 
        bytes32 customerIdHash
    ) external onlyRole(SYSTEM_ROLE) whenNotPaused nonReentrant returns (bool) {
        require(borrower != address(0), "LoanAccessControl: zero address");
        require(customerIdHash != bytes32(0), "LoanAccessControl: empty customer ID");
        require(!hasRole(BORROWER_ROLE, borrower), "LoanAccessControl: already registered");

        _grantRole(BORROWER_ROLE, borrower);
        borrowerCustomerIds[borrower] = customerIdHash;
        borrowerRegisteredAt[borrower] = block.timestamp;

        emit BorrowerRegistered(borrower, customerIdHash, block.timestamp);
        return true;
    }

    // ============ View Functions ============

    /**
     * @notice Check if an address is an active loan officer
     */
    function isActiveOfficer(address officer) external view returns (bool) {
        return activeOfficers[officer] && hasRole(LOAN_OFFICER_ROLE, officer);
    }

    /**
     * @notice Check if an address is a registered borrower
     */
    function isBorrower(address account) external view returns (bool) {
        return hasRole(BORROWER_ROLE, account);
    }

    /**
     * @notice Get officer info
     */
    function getOfficerInfo(address officer) external view returns (
        bytes32 employeeIdHash,
        bool isActive,
        uint256 registeredAt
    ) {
        return (
            officerEmployeeIds[officer],
            activeOfficers[officer],
            officerRegisteredAt[officer]
        );
    }

    /**
     * @notice Get borrower info
     */
    function getBorrowerInfo(address borrower) external view returns (
        bytes32 customerIdHash,
        uint256 registeredAt
    ) {
        return (
            borrowerCustomerIds[borrower],
            borrowerRegisteredAt[borrower]
        );
    }

    // ============ Emergency Functions ============

    /**
     * @notice Emergency pause the system
     * @param reason Reason for pausing
     */
    function emergencyPause(string calldata reason) external onlyRole(PAUSER_ROLE) returns (bool) {
        _pause();
        pauseReason = reason;
        pausedAt = block.timestamp;
        pausedBy = msg.sender;

        emit EmergencyPaused(msg.sender, reason, block.timestamp);
        return true;
    }

    /**
     * @notice Unpause the system
     */
    function unpause() external onlyRole(ADMIN_ROLE) returns (bool) {
        _unpause();
        pauseReason = "";
        pausedAt = 0;
        pausedBy = address(0);

        emit Unpaused(msg.sender, block.timestamp);
        return true;
    }

    // ============ Upgrade Functions ============

    /**
     * @notice Authorize upgrade (UUPS pattern)
     */
    function _authorizeUpgrade(address newImplementation) internal override onlyRole(UPGRADER_ROLE) {
        // Additional checks can be added here
    }
}
