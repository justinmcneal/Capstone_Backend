# CHAPTER 3

# RESULTS AND DISCUSSION

This chapter presents the results of the requirements analysis, the system features developed in response to the identified needs, and the technical and user evaluation of *MSME Pathways: A Smart Loan Support for Underserved Starting Entrepreneurs in the Informal Sector*. The presentation follows the sequence of the study objectives: (1) identifying the profile, financial behaviors, challenges, and technological needs of the intended users; (2) determining and implementing the appropriate features and functionalities of the proposed system; and (3) evaluating the system in terms of functionality, usability, clarity, usefulness, and user confidence. Quantitative findings are to be presented through frequencies, percentages, and mean ratings, while interview and observation findings are to be organized into recurring themes.

> **Drafting note:** Bracketed text identifies evidence that the researchers must still supply. It must be replaced before submission. No respondent result has been invented in this draft.

## Profile, Financial Behaviors, Challenges, and Technological Needs of the Respondents

The study involved informal-sector microentrepreneurs as the primary respondents and lending personnel as supporting respondents. The microentrepreneurs were selected because they represent the intended users of the mobile loan-support features, while the lending personnel were selected to assess the relevance of the profiling information, loan-readiness results, and officer-facing workflows. Respondents were chosen through purposive sampling based on their role, accessibility, willingness to participate, and relevance to the study.

### Profile of the Respondents

Table 2 presents the final distribution and relevant characteristics of the respondents. Only aggregated information must be reported to protect their identities.

**Table 2**  
*Profile and Distribution of Respondents*

| Respondent characteristic | Category | Frequency | Percentage |
|---|---|---:|---:|
| Respondent group | Informal-sector microentrepreneur | [Enter] | [Enter]% |
|  | Loan officer/lending personnel | [Enter] | [Enter]% |
| Age group | 18–24 | [Enter] | [Enter]% |
|  | 25–34 | [Enter] | [Enter]% |
|  | 35–44 | [Enter] | [Enter]% |
|  | 45–54 | [Enter] | [Enter]% |
|  | 55 or older | [Enter] | [Enter]% |
| Gender | Woman | [Enter] | [Enter]% |
|  | Man | [Enter] | [Enter]% |
|  | Another identity/prefer not to answer | [Enter] | [Enter]% |
| Highest educational level | [Enter category] | [Enter] | [Enter]% |
| Type of microenterprise | Sari-sari store | [Enter] | [Enter]% |
|  | Market vending | [Enter] | [Enter]% |
|  | Home-based enterprise | [Enter] | [Enter]% |
|  | Other: [Specify] | [Enter] | [Enter]% |
| Business age | Less than one year | [Enter] | [Enter]% |
|  | One to three years | [Enter] | [Enter]% |
|  | More than three years | [Enter] | [Enter]% |
| Previous borrowing experience | Formal lender | [Enter] | [Enter]% |
|  | Informal lender | [Enter] | [Enter]% |
|  | No previous loan | [Enter] | [Enter]% |
| Primary device used | Android smartphone | [Enter] | [Enter]% |
|  | iPhone | [Enter] | [Enter]% |
|  | Computer or other device | [Enter] | [Enter]% |

Table 2 shows that [write the two or three most important patterns after completing the tally]. These characteristics are relevant to the system design because [explain how the patterns affect language, navigation, accessibility, data entry, or financial guidance]. The small and purposively selected sample represents the participants included in the controlled prototype evaluation and is not intended to represent all informal-sector entrepreneurs in the Philippines.

### Financial Behaviors and Loan-Related Challenges

The interview guide examined the respondents' previous loan experiences, barriers to formal borrowing, understanding of loan information, methods of judging loan risk, and preferred forms of support. The researchers should transcribe or summarize the responses, assign anonymous codes such as ME-01 and LO-01, and group similar answers into recurring themes.

**Table 3**  
*Summary of Financial Behaviors and Loan-Related Challenges*

| Interview area | Theme derived from responses | Frequency or supporting respondent codes | Interpretation |
|---|---|---|---|
| Experience with formal or informal loans | [Enter actual theme] | [Enter] | [Discuss] |
| Barriers to formal loans | [Enter actual theme] | [Enter] | [Discuss] |
| Confusing loan information | [Enter actual theme] | [Enter] | [Discuss] |
| Method of judging loan risk | [Enter actual theme] | [Enter] | [Discuss] |
| Preferred guidance before applying | [Enter actual theme] | [Enter] | [Discuss] |
| Information respondents are willing to provide | [Enter actual theme] | [Enter] | [Discuss] |
| Privacy, trust, or usability concerns | [Enter actual theme] | [Enter] | [Discuss] |

The interview findings indicate that [insert the dominant challenge supported by the responses]. Respondents also identified [insert confusing loan concepts, such as interest, repayment schedules, penalties, or eligibility, only if supported by the data]. These findings suggest a need for [insert the corresponding system requirement]. Concerns regarding [privacy, trust, device access, or ease of use] were addressed through [state the implemented safeguard or design response].

### Technological Needs and Preferred System Support

The respondents' answers concerning chatbot assistance, desired system features, preferred guidance, and willingness to provide information were used to identify the technological requirements of the prototype. The results should be summarized in Table 4.

**Table 4**  
*Technological Needs Identified from Respondent Feedback*

| Identified need | Frequency or evidence | Priority | Design response |
|---|---:|---|---|
| Simplified explanations of loan concepts | [Enter] | [High/Medium/Low] | Loan education and AI-guided explanations |
| Loan-readiness guidance | [Enter] | [Enter] | Profile completion and readiness summary |
| Preliminary eligibility feedback | [Enter] | [Enter] | Rule-based pre-qualification with advisory output |
| Clear application status | [Enter] | [Enter] | Loan lifecycle and status tracking |
| Secure document submission | [Enter] | [Enter] | Controlled document upload and review workflow |
| Privacy and account security | [Enter] | [Enter] | Consent, authentication, authorization, and audit controls |
| Notifications and reminders | [Enter] | [Enter] | In-application, email, and real-time notifications |
| Other need identified by respondents | [Enter] | [Enter] | [Enter] |

Table 4 demonstrates how the data-gathering results were translated into system requirements. [After completing the table, discuss the highest-priority needs and explain why they were prioritized.] The resulting requirements guided the selection and refinement of features during the Scrum development cycles.

## Developed System Features and Functionalities

The second objective was to determine and implement the features required to support financial literacy, loan readiness, and preliminary lending workflows. The completed backend contains role-scoped functions for customers, loan officers, and administrators. Table 5 maps the principal needs of the intended users to the implemented system components and the evidence still required for the manuscript.

**Table 5**  
*Requirements Traceability and Implemented Features*

| User or operational need | Implemented system feature | Purpose | Manuscript evidence required |
|---|---|---|---|
| Secure system access | Registration, authentication, token and session controls, OTP, two-factor authentication, account recovery, and lockout controls | Protect accounts and restrict functions by role | Screenshots and user test result |
| Organized borrower information | Customer, personal, business, financial, address, and wallet profiles | Collect structured information needed for readiness assessment | Profile screenshots and test result |
| Loan-readiness feedback | Profile-completion summary, document-readiness status, risk-state processing, and missing-information indicators | Help users identify incomplete requirements before applying | Readiness-result screenshot and user interpretation |
| Preliminary eligibility checking | Deterministic product qualification and advisory risk output | Provide decision support without representing an official approval | Qualification screenshot and test result |
| Accessible financial guidance | English/Tagalog AI chat, streaming responses, suggestions, educational topics, frequently asked questions, and conversation history | Explain platform and loan information in accessible language | Chat screenshots and user clarity rating |
| Safe AI behavior | Consent checks, content filters, customer-scoped read-only tools, rate limits, output validation, and audit metadata | Reduce unsafe, misleading, or unauthorized AI behavior | Benchmark summary and limitation statement |
| Secure supporting documents | Presigned upload workflow, file validation, malware controls, document review, and consent-controlled AI analysis | Support document collection and controlled verification | Upload/review screenshots and test result |
| End-to-end loan workflow | Product listing, application, submission, officer assignment, review, approval or rejection, disbursement, repayment, penalties, and payoff | Support the prototype loan lifecycle for authorized roles | Workflow screenshots and functional test cases |
| Timely status information | In-application, email, and authenticated WebSocket notifications | Inform customers and staff about significant workflow events | Notification screenshot and delivery test |
| Officer and administrator oversight | Role-scoped dashboards, schedules, reports, audit records, and analytics | Support monitoring, review, and accountable administration | Dashboard screenshots and evaluator feedback |
| Transaction integrity | Ethereum-compatible smart contracts, transaction references, synchronization records, and reconciliation logic | Provide tamper-resistant references for supported integrity events | Contract test result and transaction screenshot |
| Privacy and accountability | Consent records, role-based access, sensitive-field protection, lifecycle controls, and audit logging | Protect participant and system information and support traceability | Security test summary and privacy explanation |

### Account Access and Security

The system implements separate access rules for customers, loan officers, and administrators. Authentication and account-protection functions include password hashing, token and session controls, one-time passwords, two-factor authentication, account recovery, consent handling, and lockout safeguards. Role-based authorization prevents one user group from accessing operations intended for another group. These controls address respondent concerns regarding trust and privacy and are particularly important because the prototype processes identity, business, document, and financial information.

**[Insert Figure 3: Customer registration or login interface]**

**[Insert Figure 4: Two-factor authentication or consent interface]**

### Customer Profiling and Loan Readiness

The customer-profile component organizes personal, address, business, and financial information required by the prototype. It reports completion status and identifies missing information and documents. Its readiness output is separated from official lender approval: the system provides preliminary guidance and does not claim to replace a regulated institution's underwriting process. This design supports starting entrepreneurs who may not possess conventional credit histories while maintaining clear limits on what the prototype can conclude.

**[Insert Figure 5: Customer profile and completion summary]**

**[Insert Figure 6: Loan-readiness or pre-qualification result]**

### AI-Enabled Financial Guidance

The AI-assistant component provides authenticated customers with English and Tagalog chat, streamed responses, conversation history, suggested questions, financial-education topics, and frequently asked questions. Consent is required when the feature processes personal context or conversation history. The assistant can retrieve a limited set of customer-scoped information through read-only tools, but it is restricted from guaranteeing approval, requesting credentials, or presenting itself as a substitute for professional financial or legal advice. Deterministic guidance and provider-output validation are used for stable or higher-risk requests.

**[Insert Figure 7: AI financial-guidance conversation]**

**[Insert Figure 8: Loan education or frequently asked questions]**

### Document and Loan Processing

The document component supports controlled uploads, validation, review status, and consent-dependent document analysis. The loan component supports product viewing, qualification checks, application submission, assignment to lending personnel, review decisions, document requests, disbursement records, repayment schedules, payments, penalties, and payoff operations. Authorization boundaries restrict customers to their own records and restrict officers and administrators according to their assigned responsibilities.

**[Insert Figure 9: Document submission and status]**

**[Insert Figure 10: Customer loan application and status]**

**[Insert Figure 11: Loan-officer review interface]**

### Notifications, Analytics, and Blockchain Integrity

Notifications are delivered through in-application records, email workflows, and authenticated WebSocket events for relevant loan and document changes. Analytics and audit components support role-scoped dashboards and trace significant operations. The blockchain integration records supported integrity references while sensitive personal information remains off-chain. Transaction synchronization and reconciliation logic distinguish pending, confirmed, and failed records and avoid treating a local request as confirmed before the required blockchain evidence exists.

**[Insert Figure 12: Notification or dashboard interface]**

**[Insert Figure 13: Blockchain transaction reference or verification view]**

## Evaluation of the Developed System

The third objective was to evaluate the system's effectiveness through technical testing, usability testing, and user feedback. The available repository records provide evidence of automated functional and safety testing. These records do not replace the required evaluation by the study respondents.

### Automated Functional and Technical Evaluation

Table 6 summarizes existing automated evidence. The figures are taken from dated project verification records and should be accompanied by test-report screenshots or exported reports in the appendices. They were not rerun specifically for this manuscript draft.

**Table 6**  
*Summary of Existing Automated Technical Evidence*

| Evaluation area | Recorded result | Interpretation and limitation |
|---|---:|---|
| Full repository regression, August 15, 2026 | 1,276 passed; 39 skipped | The tested local behaviors passed. Skipped opt-in integration tests are not passing results and require approved external environments. |
| Loan and blockchain-related selection, August 15, 2026 | 510 passed; 13 skipped; 713 deselected | The selected loan, permission, qualification, payment, disbursement, audit, task, and blockchain behaviors passed locally; real-service evidence remains limited. |
| Focused AI safety, knowledge, chat, and streaming regression, August 15, 2026 | 94 passed | The focused local AI interface and safety behaviors passed. |
| AI system-level bilingual quality benchmark | 18 of 18 passed | The complete controlled system passed the configured synthetic benchmark after deterministic guidance and output validation. This does not mean the raw language model independently achieved 100% accuracy. |
| Raw-model benchmark before deterministic containment | 13 of 18 passed; 100% of critical cases passed | The raw-model result documents remaining variability and explains why controlled guidance is required. |
| Disbursement smart-contract component, March 14, 2026 | 49 of 49 passed; 100% statement, function, and line coverage | Unit-level evidence supports the tested contract component; real-chain deployment and operational evidence remain separate. |

The technical results show that the tested application logic has broad automated coverage across authentication, profiles, documents, AI guidance, qualification, loan processing, notifications, analytics, and blockchain-related operations. The latest documented full regression reported no failures among executed tests. However, the skipped tests require real or approved MongoDB, Redis/Celery, object storage, malware-scanning, provider, proxy, load, or blockchain environments. Therefore, the results establish local prototype reliability for the executed cases but do not establish production readiness or large-scale operational performance.

The AI benchmark also requires careful interpretation. The system-level result reached 18 out of 18 controlled cases because it combines provider-independent safety controls, deterministic guidance, and validated provider output. The separately documented raw-model result was 13 out of 18. Consequently, the system should be described as a controlled decision-support and education feature rather than an autonomous or infallible financial adviser.

### Respondent Usability and Usefulness Evaluation

The post-interaction questionnaire must use the rating scale approved in the research instrument. If a five-point agreement scale is approved, the researchers may compute each item's mean using:

\[
\bar{x} = \frac{\sum fx}{N}
\]

where \(f\) is the number of responses for each rating, \(x\) is the rating value, and \(N\) is the number of valid responses. The exact verbal-interpretation intervals must be placed in Chapter 2 and applied consistently here.

**Table 7**  
*Microentrepreneur Evaluation of the System*

| Evaluation statement | Mean | Verbal interpretation | Rank |
|---|---:|---|---:|
| The system was easy to navigate. | [Enter] | [Enter] | [Enter] |
| The labels and instructions were understandable. | [Enter] | [Enter] | [Enter] |
| The loan explanations were clear. | [Enter] | [Enter] | [Enter] |
| The chatbot provided relevant guidance. | [Enter] | [Enter] | [Enter] |
| The readiness result was understandable. | [Enter] | [Enter] | [Enter] |
| The system helped me recognize information needed before applying. | [Enter] | [Enter] | [Enter] |
| The security and privacy notices were clear. | [Enter] | [Enter] | [Enter] |
| I would feel confident using the system for loan preparation. | [Enter] | [Enter] | [Enter] |
| **Overall mean** | **[Enter]** | **[Enter]** |  |

Table 7 indicates that [state the actual overall mean and interpretation]. The highest-rated item was [enter item and mean], suggesting that [interpretation]. The lowest-rated item was [enter item and mean], indicating that [explain the improvement needed]. Because the evaluation involved a small purposive sample, the ratings describe the experience of the participating respondents and should not be generalized to the wider population.

**Table 8**  
*Loan Officer or Lending Personnel Evaluation of the System*

| Evaluation statement | Mean or rating | Verbal interpretation | Supporting comment |
|---|---:|---|---|
| Borrower information was organized and understandable. | [Enter] | [Enter] | [Enter] |
| Readiness and qualification outputs were clearly presented. | [Enter] | [Enter] | [Enter] |
| The review workflow was appropriate for preliminary assessment. | [Enter] | [Enter] | [Enter] |
| Status and document information supported the review task. | [Enter] | [Enter] | [Enter] |
| Audit and transaction references improved traceability. | [Enter] | [Enter] | [Enter] |
| The system was useful as a decision-support prototype. | [Enter] | [Enter] | [Enter] |
| **Overall mean or rating** | **[Enter]** | **[Enter]** |  |

The lending-personnel evaluation shows that [insert the actual result]. The evaluator particularly noted [insert verified comment], while [insert feature or concern] required further improvement. If only one lending respondent participates, the result must be reported as an individual expert or stakeholder assessment rather than a broadly generalizable statistical finding.

### Change in Loan Understanding, Readiness, and Confidence

The third research objective uses the term *improving*, which requires evidence of change rather than only a satisfaction rating after system use. Subject to adviser and instrument approval, the same respondents should answer aligned questions before and after interacting with the prototype. With the proposed small sample, the researchers should report individual and descriptive change scores and avoid unsupported claims of statistical significance.

**Table 9**  
*Pre-Interaction and Post-Interaction Assessment Results*

| Evaluation indicator | Pre-interaction mean | Post-interaction mean | Mean change | Interpretation |
|---|---:|---:|---:|---|
| Understanding of interest, repayment terms, and penalties | [Enter] | [Enter] | [Enter] | [Enter] |
| Ability to recognize a risky or unsuitable loan offer | [Enter] | [Enter] | [Enter] | [Enter] |
| Knowledge of information and documents needed before applying | [Enter] | [Enter] | [Enter] | [Enter] |
| Understanding of loan-readiness or qualification results | [Enter] | [Enter] | [Enter] | [Enter] |
| Confidence in preparing for a formal loan application | [Enter] | [Enter] | [Enter] | [Enter] |
| **Overall mean** | **[Enter]** | **[Enter]** | **[Enter]** | **[Enter]** |

Table 9 shows that the overall mean changed from [enter pre-interaction mean] before prototype use to [enter post-interaction mean] after prototype use, representing a descriptive change of [enter value]. The greatest change was observed in [enter indicator], while the smallest change was recorded for [enter indicator]. These findings [support/do not support] the conclusion that the prototype improved the participating respondents' loan understanding, readiness, or confidence within the controlled evaluation session. The result must not be generalized beyond the approved participants.

If no baseline measurement was collected, Table 9 and all claims of *improvement* must be removed. In that case, Objective 3 and the corresponding research question should be revised, with adviser approval, to evaluate perceived usability, clarity, usefulness, and confidence after system use.

### User Feedback and Observed Issues

Open-ended survey responses and observation notes should be grouped according to repeated comments and observed interaction problems.

**Table 10**  
*Summary of User Feedback and System Revisions*

| Feedback or observed issue | Respondent evidence | Revision made or recommended | Status |
|---|---|---|---|
| [Enter actual feedback] | [Anonymous code/frequency] | [Enter action] | [Completed/Pending] |
| [Enter actual feedback] | [Anonymous code/frequency] | [Enter action] | [Completed/Pending] |
| [Enter actual feedback] | [Anonymous code/frequency] | [Enter action] | [Completed/Pending] |

The feedback demonstrates that [summarize the most important actual user response]. Changes completed during or after evaluation included [enter only changes actually made]. Suggestions outside the prototype scope included [enter suggestions], which may be considered in future development.

## Summary of Findings

Based on the results available at the time of drafting, the following findings were obtained:

1. **Respondent needs and challenges.** [Insert a concise answer to Research Question 1 based on the completed profile table, interview themes, and observation notes. State the most common barriers, confusing loan concepts, desired guidance, and technological concerns.]

2. **System features and functionalities.** The requirements were translated into an integrated prototype containing secure role-based accounts, customer and business profiling, readiness and qualification support, AI-enabled English/Tagalog guidance, document processing, loan workflows, notifications, dashboards, audit records, and blockchain-integrity components. The traceability analysis shows how these components correspond to financial-guidance, preparedness, security, and preliminary-review needs.

3. **System effectiveness.** Existing automated evidence supports the functionality of the executed local test cases, including a documented full regression result of 1,276 passed tests and a controlled AI system-level benchmark result of 18 out of 18. Nevertheless, external integration and production deployment evidence remains incomplete. [Add the actual usability overall mean, loan-officer result, pre/post descriptive change if collected, user-confidence result, and dominant feedback theme.] Only after these respondent results are inserted can the study make a complete conclusion concerning usability and effectiveness.

## Conclusions

The study concludes that *MSME Pathways* was developed as an integrated prototype that responds to the intended functions of financial education, loan-readiness preparation, preliminary qualification support, document and loan workflow management, and transaction traceability. Its architecture and implemented controls support differentiated customer, loan-officer, and administrator responsibilities while treating AI output as advisory and keeping sensitive information outside blockchain records.

The existing automated results indicate that the executed local functional, security, safety, and contract tests behaved as expected. They do not, by themselves, establish that the system improves the financial understanding, readiness, or confidence of the target users. **[Insert the human-evaluation conclusion here after calculating the questionnaire results and analyzing the interviews.]** The final conclusion must remain limited to the controlled prototype, the approved respondents, the evaluation period, and the available infrastructure.

## Recommendations

Based on the implementation and currently available technical findings, the researchers recommend the following:

1. Complete the approved usability and stakeholder evaluation and use the results to refine navigation, wording, readiness explanations, and privacy notices.
2. Conduct future studies with a larger and more diverse group of informal-sector entrepreneurs and lending personnel to improve the generalizability of the findings.
3. Validate the system in approved deployment environments, including MongoDB, Redis/Celery, storage, malware scanning, AI provider, proxy, monitoring, and blockchain services, before production use.
4. Continue evaluating English and Tagalog AI responses for accuracy, groundedness, clarity, bias, safety, and consistency, while retaining deterministic controls for high-risk financial guidance.
5. Expand document-model evaluation using appropriately consented and representative holdout data and report per-class precision, recall, F1 score, confusion matrix, and subgroup limitations before relying on the model operationally.
6. Improve accessibility through plain-language content, readable interfaces, guided data entry, and testing on the devices and network conditions used by the target population.
7. Seek legal, privacy, security, and institutional review before connecting the prototype to live lenders, payment services, credit bureaus, wallets, or production blockchain networks.
8. Preserve the system's stated limitation that readiness, risk, chatbot, and qualification outputs are educational or decision-support results and do not constitute guaranteed loan approval or professional financial advice.
9. Add the respondents' actual recommendations from Table 10: **[Insert respondent-supported recommendation(s)].**
