// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";

/**
 * @title LoanToken
 * @notice ERC20 token for the MSME Pathways Loan System
 * @dev This token can be used for:
 *      - Loan disbursements (treasury → borrower)
 *      - Loan repayments (borrower → treasury)
 *      - Collateral (if needed in future)
 * 
 * Features:
 * - Mintable by MINTER_ROLE (for initial supply and future minting)
 * - Burnable (for supply management)
 * - Pausable (for emergencies)
 * - Permit (gasless approvals via EIP-2612)
 */
contract LoanToken is ERC20, ERC20Burnable, ERC20Permit, AccessControl, Pausable {
    
    // ============ Roles ============
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");
    bytes32 public constant TREASURY_ROLE = keccak256("TREASURY_ROLE");

    // ============ State Variables ============
    uint256 public maxSupply;
    address public treasury;
    
    // ============ Events ============
    event TreasuryUpdated(address indexed oldTreasury, address indexed newTreasury);
    event MaxSupplyUpdated(uint256 oldMaxSupply, uint256 newMaxSupply);

    /**
     * @notice Initializes the LoanToken contract
     * @param name Token name (e.g., "MSME Pathway Token")
     * @param symbol Token symbol (e.g., "MPT")
     * @param initialSupply Initial token supply (with 18 decimals)
     * @param _treasury Address of the treasury
     * @param _maxSupply Maximum supply cap (0 for unlimited)
     */
    constructor(
        string memory name,
        string memory symbol,
        uint256 initialSupply,
        address _treasury,
        uint256 _maxSupply
    ) ERC20(name, symbol) ERC20Permit(name) {
        require(_treasury != address(0), "Treasury cannot be zero address");
        
        // Grant roles
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(MINTER_ROLE, msg.sender);
        _grantRole(PAUSER_ROLE, msg.sender);
        _grantRole(TREASURY_ROLE, _treasury);

        treasury = _treasury;
        maxSupply = _maxSupply;

        // Mint initial supply to treasury
        if (initialSupply > 0) {
            _mint(_treasury, initialSupply);
        }
    }

    // ============ Minting Functions ============

    /**
     * @notice Mint new tokens
     * @param to Recipient address
     * @param amount Amount to mint (with decimals)
     */
    function mint(address to, uint256 amount) public onlyRole(MINTER_ROLE) {
        if (maxSupply > 0) {
            require(totalSupply() + amount <= maxSupply, "Would exceed max supply");
        }
        _mint(to, amount);
    }

    /**
     * @notice Mint tokens directly to treasury
     * @param amount Amount to mint
     */
    function mintToTreasury(uint256 amount) public onlyRole(MINTER_ROLE) {
        mint(treasury, amount);
    }

    // ============ Treasury Functions ============

    /**
     * @notice Update treasury address
     * @param newTreasury New treasury address
     */
    function setTreasury(address newTreasury) public onlyRole(DEFAULT_ADMIN_ROLE) {
        require(newTreasury != address(0), "Treasury cannot be zero address");
        
        address oldTreasury = treasury;
        
        // Revoke role from old treasury
        _revokeRole(TREASURY_ROLE, oldTreasury);
        
        // Grant role to new treasury
        _grantRole(TREASURY_ROLE, newTreasury);
        
        treasury = newTreasury;
        
        emit TreasuryUpdated(oldTreasury, newTreasury);
    }

    /**
     * @notice Update max supply cap
     * @param newMaxSupply New maximum supply (0 for unlimited)
     */
    function setMaxSupply(uint256 newMaxSupply) public onlyRole(DEFAULT_ADMIN_ROLE) {
        require(newMaxSupply == 0 || newMaxSupply >= totalSupply(), "New max below current supply");
        
        uint256 oldMaxSupply = maxSupply;
        maxSupply = newMaxSupply;
        
        emit MaxSupplyUpdated(oldMaxSupply, newMaxSupply);
    }

    // ============ Pause Functions ============

    /**
     * @notice Pause all token transfers
     */
    function pause() public onlyRole(PAUSER_ROLE) {
        _pause();
    }

    /**
     * @notice Unpause token transfers
     */
    function unpause() public onlyRole(PAUSER_ROLE) {
        _unpause();
    }

    // ============ Transfer Hooks ============

    // ============ Transfer Hooks ============

    /**
     * @dev Override update to add pausable functionality
     * In OZ v5, _beforeTokenTransfer was replaced with _update
     */
    function _update(
        address from,
        address to,
        uint256 value
    ) internal override whenNotPaused {
        super._update(from, to, value);
    }

    // ============ View Functions ============

    /**
     * @notice Get remaining mintable supply
     * @return Remaining tokens that can be minted (0 if unlimited)
     */
    function remainingMintableSupply() public view returns (uint256) {
        if (maxSupply == 0) {
            return type(uint256).max; // Unlimited
        }
        return maxSupply - totalSupply();
    }

    /**
     * @notice Check if address is treasury
     * @param account Address to check
     * @return True if address has TREASURY_ROLE
     */
    function isTreasury(address account) public view returns (bool) {
        return hasRole(TREASURY_ROLE, account);
    }

    /**
     * @notice Returns number of decimals (18)
     */
    function decimals() public pure override returns (uint8) {
        return 18;
    }
}
