// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

/**
 * @title LoanOracle
 * @notice Oracle contract for off-chain data (AI scores, payment confirmations)
 * @dev Bridges off-chain AI analysis and payment gateway confirmations
 */
contract LoanOracle is 
    Initializable,
    AccessControlUpgradeable,
    UUPSUpgradeable 
{
    // ============ Type Definitions ============
    struct AIScore {
        bytes32 loanId;
        uint8 eligibilityScore;          // 0-100
        uint8 riskCategory;              // 0=Low, 1=Medium, 2=High
        uint256 recommendedAmount;
        bytes32 analysisHash;            // Hash of full AI analysis
        uint256 timestamp;
        bool isValid;
    }

    struct ExternalPayment {
        bytes32 loanId;
        bytes32 externalReference;
        uint256 amount;
        uint256 confirmedAt;
        address confirmedBy;
        bool isConfirmed;
    }

    // ============ Constants ============
    uint256 public constant VERSION = 1;
    uint256 public constant SCORE_VALIDITY_PERIOD = 7 days;
    
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ State Variables ============
    // AI Scores
    mapping(bytes32 => AIScore) public aiScores;
    
    // External Payments
    mapping(bytes32 => ExternalPayment) public externalPayments;
    mapping(bytes32 => bool) public confirmedReferences;

    // Statistics
    uint256 public totalScoresSubmitted;
    uint256 public totalPaymentsConfirmed;

    // ============ Events ============
    event AIScoreSubmitted(
        bytes32 indexed loanId,
        uint8 eligibilityScore,
        uint8 riskCategory,
        uint256 recommendedAmount,
        bytes32 analysisHash,
        uint256 timestamp
    );

    event AIScoreInvalidated(
        bytes32 indexed loanId,
        address indexed invalidatedBy,
        uint256 timestamp
    );

    event PaymentConfirmed(
        bytes32 indexed loanId,
        bytes32 indexed externalReference,
        uint256 amount,
        address confirmedBy,
        uint256 timestamp
    );

    event OracleAddressUpdated(
        address indexed oldOracle,
        address indexed newOracle,
        uint256 timestamp
    );

    // ============ Errors ============
    error ScoreAlreadyExists(bytes32 loanId);
    error ScoreNotFound(bytes32 loanId);
    error InvalidScore(uint8 score);
    error PaymentAlreadyConfirmed(bytes32 paymentRef);

    // ============ Initializer ============
    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /**
     * @notice Initialize the contract
     */
    function initialize(address admin, address oracle) public initializer {
        require(admin != address(0), "Zero address");

        __AccessControl_init();
        __UUPSUpgradeable_init();

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        _grantRole(UPGRADER_ROLE, admin);
        
        if (oracle != address(0)) {
            _grantRole(ORACLE_ROLE, oracle);
        }
    }

    // ============ AI Score Functions ============

    /**
     * @notice Submit AI score for a loan application
     * @param loanId Loan identifier
     * @param eligibilityScore Score from 0-100
     * @param riskCategory 0=Low, 1=Medium, 2=High
     * @param recommendedAmount Recommended loan amount
     * @param analysisHash Hash of full AI analysis
     */
    function submitAIScore(
        bytes32 loanId,
        uint8 eligibilityScore,
        uint8 riskCategory,
        uint256 recommendedAmount,
        bytes32 analysisHash
    ) external onlyRole(ORACLE_ROLE) returns (bool) {
        if (eligibilityScore > 100) {
            revert InvalidScore(eligibilityScore);
        }
        require(riskCategory <= 2, "LoanOracle: invalid risk category");

        // Allow overwriting stale scores
        AIScore storage existing = aiScores[loanId];
        if (existing.isValid && block.timestamp < existing.timestamp + SCORE_VALIDITY_PERIOD) {
            revert ScoreAlreadyExists(loanId);
        }

        AIScore storage score = aiScores[loanId];
        score.loanId = loanId;
        score.eligibilityScore = eligibilityScore;
        score.riskCategory = riskCategory;
        score.recommendedAmount = recommendedAmount;
        score.analysisHash = analysisHash;
        score.timestamp = block.timestamp;
        score.isValid = true;

        totalScoresSubmitted++;

        emit AIScoreSubmitted(
            loanId,
            eligibilityScore,
            riskCategory,
            recommendedAmount,
            analysisHash,
            block.timestamp
        );

        return true;
    }

    /**
     * @notice Invalidate an AI score (if error detected)
     */
    function invalidateScore(bytes32 loanId) external onlyRole(ADMIN_ROLE) returns (bool) {
        AIScore storage score = aiScores[loanId];
        if (!score.isValid) {
            revert ScoreNotFound(loanId);
        }

        score.isValid = false;

        emit AIScoreInvalidated(loanId, msg.sender, block.timestamp);
        return true;
    }

    /**
     * @notice Get AI score for a loan
     */
    function getAIScore(bytes32 loanId) external view returns (AIScore memory) {
        return aiScores[loanId];
    }

    /**
     * @notice Check if score is valid and not expired
     */
    function isScoreValid(bytes32 loanId) external view returns (bool) {
        AIScore storage score = aiScores[loanId];
        return score.isValid && block.timestamp < score.timestamp + SCORE_VALIDITY_PERIOD;
    }

    // ============ External Payment Functions ============

    /**
     * @notice Confirm an external payment (from payment gateway)
     * @param loanId Loan identifier
     * @param externalReference External reference number (hash)
     * @param amount Payment amount
     */
    function confirmExternalPayment(
        bytes32 loanId,
        bytes32 externalReference,
        uint256 amount
    ) external onlyRole(ORACLE_ROLE) returns (bool) {
        require(loanId != bytes32(0), "LoanOracle: empty loan ID");
        require(externalReference != bytes32(0), "LoanOracle: empty reference");
        require(amount > 0, "LoanOracle: invalid amount");

        if (confirmedReferences[externalReference]) {
            revert PaymentAlreadyConfirmed(externalReference);
        }

        ExternalPayment storage payment = externalPayments[externalReference];
        payment.loanId = loanId;
        payment.externalReference = externalReference;
        payment.amount = amount;
        payment.confirmedAt = block.timestamp;
        payment.confirmedBy = msg.sender;
        payment.isConfirmed = true;

        confirmedReferences[externalReference] = true;
        totalPaymentsConfirmed++;

        emit PaymentConfirmed(
            loanId,
            externalReference,
            amount,
            msg.sender,
            block.timestamp
        );

        return true;
    }

    /**
     * @notice Batch confirm multiple payments
     */
    function confirmPaymentsBatch(
        bytes32[] calldata loanIds,
        bytes32[] calldata externalReferences,
        uint256[] calldata amounts
    ) external onlyRole(ORACLE_ROLE) returns (uint256 confirmed) {
        require(
            loanIds.length == externalReferences.length &&
            loanIds.length == amounts.length,
            "LoanOracle: array mismatch"
        );
        require(loanIds.length <= 50, "LoanOracle: batch too large");

        for (uint256 i = 0; i < loanIds.length; i++) {
            if (confirmedReferences[externalReferences[i]]) {
                continue; // Skip already confirmed
            }

            ExternalPayment storage payment = externalPayments[externalReferences[i]];
            payment.loanId = loanIds[i];
            payment.externalReference = externalReferences[i];
            payment.amount = amounts[i];
            payment.confirmedAt = block.timestamp;
            payment.confirmedBy = msg.sender;
            payment.isConfirmed = true;

            confirmedReferences[externalReferences[i]] = true;
            totalPaymentsConfirmed++;
            confirmed++;

            emit PaymentConfirmed(
                loanIds[i],
                externalReferences[i],
                amounts[i],
                msg.sender,
                block.timestamp
            );
        }

        return confirmed;
    }

    /**
     * @notice Check if a payment is confirmed
     */
    function isPaymentConfirmed(bytes32 loanId, bytes32 paymentRef) external view returns (bool) {
        ExternalPayment storage payment = externalPayments[paymentRef];
        return payment.isConfirmed && payment.loanId == loanId;
    }

    /**
     * @notice Get external payment details
     */
    function getExternalPayment(bytes32 paymentRef) external view returns (ExternalPayment memory) {
        return externalPayments[paymentRef];
    }

    // ============ Admin Functions ============

    /**
     * @notice Add a new oracle address
     */
    function addOracle(address oracle) external onlyRole(ADMIN_ROLE) {
        require(oracle != address(0), "LoanOracle: zero address");
        _grantRole(ORACLE_ROLE, oracle);
        emit OracleAddressUpdated(address(0), oracle, block.timestamp);
    }

    /**
     * @notice Remove an oracle address
     */
    function removeOracle(address oracle) external onlyRole(ADMIN_ROLE) {
        _revokeRole(ORACLE_ROLE, oracle);
        emit OracleAddressUpdated(oracle, address(0), block.timestamp);
    }

    // ============ View Functions ============

    /**
     * @notice Get statistics
     */
    function getStats() external view returns (
        uint256 _totalScoresSubmitted,
        uint256 _totalPaymentsConfirmed
    ) {
        return (totalScoresSubmitted, totalPaymentsConfirmed);
    }

    // ============ Upgrade Functions ============

    function _authorizeUpgrade(address newImplementation) internal override onlyRole(UPGRADER_ROLE) {}
}
