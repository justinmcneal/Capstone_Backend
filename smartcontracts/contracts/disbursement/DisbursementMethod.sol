// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import "../interfaces/ILoanApplication.sol";
import "../interfaces/ILoanAccessControl.sol";
import "../interfaces/IAuditRegistry.sol";

/**
 * @title DisbursementMethod
 * @notice Manages borrower's preferred disbursement method selection
 * @dev Separated from disbursement execution for single responsibility
 * @custom:security-contact security@msme-platform.com
 */
contract DisbursementMethod is 
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable
{
    // ============ Constants ============
    uint256 public constant VERSION = 1;
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant SYSTEM_ROLE = keccak256("SYSTEM_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ Enums ============
    
    /**
     * @notice Available disbursement methods
     */
    enum Method {
        BankTransfer,    // 0 - Direct bank transfer
        GCash,           // 1 - GCash mobile wallet
        Cash,            // 2 - Cash pickup
        Maya,            // 3 - Maya (formerly PayMaya)
        Other            // 4 - Other methods
    }

    // ============ Structs ============
    
    /**
     * @notice Disbursement method selection record
     */
    struct MethodSelection {
        bytes32 loanId;
        uint256 selectedAt;
        uint256 updatedAt;
        address borrower;            // 20 bytes — packed with method + isLocked
        Method method;               // 1 byte
        bool isLocked;               // 1 byte — Locked after disbursement initiated
    }

    // ============ State Variables ============
    ILoanAccessControl public accessControl;
    IAuditRegistry public auditRegistry;
    ILoanApplication public loanApplication;

    // Method storage
    mapping(bytes32 => MethodSelection) private methodSelections;
    mapping(bytes32 => bool) private hasMethod;
    
    // Statistics
    uint256 public totalMethodsSet;
    uint256 public totalMethodsUpdated;

    // ============ Events ============
    
    event DisbursementMethodSelected(
        bytes32 indexed loanId,
        address indexed borrower,
        Method method,
        uint256 timestamp
    );

    event DisbursementMethodUpdated(
        bytes32 indexed loanId,
        address indexed borrower,
        Method oldMethod,
        Method newMethod,
        uint256 timestamp
    );

    event DisbursementMethodLocked(
        bytes32 indexed loanId,
        Method method,
        uint256 timestamp
    );

    // ============ Errors ============
    
    error ZeroAddress();
    error LoanNotFound(bytes32 loanId);
    error InvalidLoanStatus(bytes32 loanId, ILoanApplication.LoanStatus current);
    error NotBorrower(address caller, address borrower);
    error MethodAlreadyLocked(bytes32 loanId);
    error MethodNotSet(bytes32 loanId);

    // ============ Modifiers ============
    
    modifier onlyBorrower(bytes32 loanId) {
        ILoanApplication.Application memory app = loanApplication.getApplication(loanId);
        if (msg.sender != app.borrower) {
            revert NotBorrower(msg.sender, app.borrower);
        }
        _;
    }

    modifier loanExists(bytes32 loanId) {
        if (!loanApplication.exists(loanId)) {
            revert LoanNotFound(loanId);
        }
        _;
    }

    modifier methodNotLocked(bytes32 loanId) {
        if (hasMethod[loanId] && methodSelections[loanId].isLocked) {
            revert MethodAlreadyLocked(loanId);
        }
        _;
    }

    // ============ Initialization ============
    
    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /**
     * @notice Initialize the contract
     * @param _accessControl Address of LoanAccessControl contract
     * @param _auditRegistry Address of AuditRegistry contract
     * @param _loanApplication Address of LoanApplication contract
     * @param _admin Address of the admin
     */
    function initialize(
        address _accessControl,
        address _auditRegistry,
        address _loanApplication,
        address _admin
    ) public initializer {
        if (_accessControl == address(0) || 
            _auditRegistry == address(0) || 
            _loanApplication == address(0) ||
            _admin == address(0)) {
            revert ZeroAddress();
        }

        __AccessControl_init();
        __ReentrancyGuard_init();
        __Pausable_init();
        __UUPSUpgradeable_init();

        accessControl = ILoanAccessControl(_accessControl);
        auditRegistry = IAuditRegistry(_auditRegistry);
        loanApplication = ILoanApplication(_loanApplication);

        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(ADMIN_ROLE, _admin);
        _grantRole(UPGRADER_ROLE, _admin);
    }

    // ============ Core Functions ============
    
    /**
     * @notice Set preferred disbursement method for a loan
     * @param loanId The loan identifier
     * @param method The preferred disbursement method
     * @return success True if method set successfully
     */
    function setPreferredMethod(
        bytes32 loanId,
        Method method
    ) 
        external 
        nonReentrant 
        whenNotPaused 
        loanExists(loanId)
        onlyBorrower(loanId)
        methodNotLocked(loanId)
        returns (bool success)
    {
        // Get loan details (enum validation is automatic in Solidity 0.8.x)
        ILoanApplication.Application memory app = loanApplication.getApplication(loanId);
        
        // Loan must be in Approved status
        if (app.status != ILoanApplication.LoanStatus.Approved) {
            revert InvalidLoanStatus(loanId, app.status);
        }

        bool isUpdate = hasMethod[loanId];
        Method oldMethod;

        if (isUpdate) {
            // Update existing method
            oldMethod = methodSelections[loanId].method;
            methodSelections[loanId].method = method;
            methodSelections[loanId].updatedAt = block.timestamp;
            
            totalMethodsUpdated++;

            emit DisbursementMethodUpdated(
                loanId,
                msg.sender,
                oldMethod,
                method,
                block.timestamp
            );
        } else {
            // Set new method
            methodSelections[loanId] = MethodSelection({
                loanId: loanId,
                borrower: msg.sender,
                method: method,
                selectedAt: block.timestamp,
                updatedAt: block.timestamp,
                isLocked: false
            });
            
            hasMethod[loanId] = true;
            totalMethodsSet++;

            emit DisbursementMethodSelected(
                loanId,
                msg.sender,
                method,
                block.timestamp
            );
        }

        // Log to audit registry
        auditRegistry.log(
            loanId,
            "disbursement_method",
            isUpdate ? IAuditRegistry.AuditAction.SystemConfigChanged : IAuditRegistry.AuditAction.SystemConfigChanged,
            bytes32(uint256(method)),
            isUpdate ? bytes32(uint256(oldMethod)) : bytes32(0),
            bytes32(uint256(method))
        );

        return true;
    }

    /**
     * @notice Lock disbursement method (called by DisbursementExecution)
     * @param loanId The loan identifier
     * @return success True if method locked successfully
     */
    function lockMethod(bytes32 loanId) 
        external 
        nonReentrant
        whenNotPaused
        returns (bool success) 
    {
        // Only SYSTEM_ROLE (DisbursementExecution contract) can lock
        if (!hasRole(SYSTEM_ROLE, msg.sender)) {
            revert NotBorrower(msg.sender, address(0));
        }

        if (!hasMethod[loanId]) {
            revert MethodNotSet(loanId);
        }

        if (methodSelections[loanId].isLocked) {
            revert MethodAlreadyLocked(loanId);
        }

        methodSelections[loanId].isLocked = true;

        emit DisbursementMethodLocked(
            loanId,
            methodSelections[loanId].method,
            block.timestamp
        );

        return true;
    }

    // ============ View Functions ============
    
    /**
     * @notice Get preferred disbursement method for a loan
     * @param loanId The loan identifier
     * @return method The preferred disbursement method
     */
    function getPreferredMethod(bytes32 loanId) 
        external 
        view 
        loanExists(loanId)
        returns (Method method) 
    {
        if (!hasMethod[loanId]) {
            revert MethodNotSet(loanId);
        }
        return methodSelections[loanId].method;
    }

    /**
     * @notice Check if loan has a preferred method set
     * @param loanId The loan identifier
     * @return hasMethodSet True if method is set
     */
    function hasPreferredMethod(bytes32 loanId) 
        external 
        view 
        returns (bool hasMethodSet) 
    {
        return hasMethod[loanId];
    }

    /**
     * @notice Get complete method selection details
     * @param loanId The loan identifier
     * @return selection Complete MethodSelection struct
     */
    function getMethodSelection(bytes32 loanId) 
        external 
        view 
        loanExists(loanId)
        returns (MethodSelection memory selection) 
    {
        if (!hasMethod[loanId]) {
            revert MethodNotSet(loanId);
        }
        return methodSelections[loanId];
    }

    /**
     * @notice Check if method is locked
     * @param loanId The loan identifier
     * @return isLocked True if method is locked
     */
    function isMethodLocked(bytes32 loanId) 
        external 
        view 
        returns (bool isLocked) 
    {
        if (!hasMethod[loanId]) {
            return false;
        }
        return methodSelections[loanId].isLocked;
    }

    /**
     * @notice Get contract statistics
     * @return _totalMethodsSet Total methods set
     * @return _totalMethodsUpdated Total methods updated
     */
    function getStats() 
        external 
        view 
        returns (
            uint256 _totalMethodsSet,
            uint256 _totalMethodsUpdated
        ) 
    {
        return (totalMethodsSet, totalMethodsUpdated);
    }

    // ============ Admin Functions ============
    
    /**
     * @notice Pause contract (emergency stop)
     */
    function pause() external onlyRole(ADMIN_ROLE) {
        _pause();
    }

    /**
     * @notice Unpause contract
     */
    function unpause() external onlyRole(ADMIN_ROLE) {
        _unpause();
    }

    /**
     * @notice Grant SYSTEM_ROLE to an address
     * @param account Address to grant role to
     */
    function grantSystemRole(address account) external onlyRole(ADMIN_ROLE) {
        grantRole(SYSTEM_ROLE, account);
    }

    /**
     * @notice Revoke SYSTEM_ROLE from an address
     * @param account Address to revoke role from
     */
    function revokeSystemRole(address account) external onlyRole(ADMIN_ROLE) {
        revokeRole(SYSTEM_ROLE, account);
    }

    // ============ Upgrade Authorization ============
    
    /**
     * @notice Authorize contract upgrade
     * @param newImplementation Address of new implementation
     */
    function _authorizeUpgrade(address newImplementation) 
        internal 
        override 
        onlyRole(UPGRADER_ROLE) 
    {
        // Intentionally empty - authorization handled by modifier
    }
}
