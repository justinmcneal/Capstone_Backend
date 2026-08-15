# MSME Pathways: 50% Milestone Presentation Package

## Important Status Wording

Use this wording in the slides and narration:

> The required checkpoint is 50%, while the team estimates that roughly 80% of the core system is already implemented across the backend, web, and mobile applications. The remaining work is concentrated on loan and payment hardening, notification reliability, cross-platform regression testing, and staging or deployment validation.

The backend repository supports the claim that the major modules are already implemented. However, the 80% figure is a **team estimate** because the web and mobile repositories were not reviewed for this document. Avoid saying that only loans and notifications remain, since final integration, testing, configuration, and documentation work are also necessary.

## Basis from the Submitted `msme_group_6-1.pdf`

The following names, roles, timeline, and task assignments were transcribed from the four-page plan submitted to the professor. Confirm the exact spelling of every name before submission.

| Member | Submitted Role |
|---|---|
| Justin Mc Neal G. Caronongan | Project Manager |
| Eli Gabriel T. Soriano | System Developer |
| Joshua S. Co | System Designer |
| John Lloyd Pimentel | Researcher |
| Feniel A. Bartie | Document Writer |

## Recommended Slide Deck

Use six short slides. Keep the recorded presentation between **2 minutes 40 seconds and 2 minutes 50 seconds** to stay safely below the three-minute limit.

### Slide 1 — Title and Milestone Status

**Put on the slide:**

- MSME Pathways: Smart Loan Support for the Informal Sector
- 50% Milestone Checking
- Team Group 6
- Required checkpoint: 50%
- Team-estimated core completion: approximately 80%
- Names and roles of the five members

**Suggested visual:** One clean screenshot showing the web dashboard beside two mobile screens. Do not place paragraphs on this slide.

### Slide 2 — Project Timeline

**Put on the slide:**

| Week and Date | Planned Output | Milestone Status |
|---|---|---|
| Week 2 — July 18 | Finalize scope, backlog, team roles, and deliverables | Completed |
| Week 3 — July 25 | Track progress and enable or verify S3 document storage in staging | Completed or demonstrated locally |
| Week 4 — August 1 | Finish Chapter 3 draft, architecture, diagrams, and technology stack | Completed |
| Week 5 — August 8 | End-to-end integration of web, backend, mobile, and WebSocket flows | Core flow completed; continuing regression checks |
| Week 6 — August 15 | Functional and security testing: 2FA, role guards, input validation, and state transitions | In progress at milestone check |
| Week 7 — August 22 | Performance and reliability checks | Started early in the backend; further checks planned |
| Week 8 — August 29 | Finish Chapter 4 | Planned |
| Week 9 — September 5 | Final manuscript formatting and proofreading | Planned |
| Week 10 — September 12 | Defense slides, demo script, Q&A, and dry run | Planned |
| Weeks 11–12 — September 19–26 | Final hardening, regression fixes, final video, and manuscript submission | Planned |
| Weeks 13–18 — October 3 to November 7 | Preparation for project defense | Planned |

**Suggested visual:** A horizontal timeline. Color completed items green, current work orange, and planned work gray.

### Slide 3 — Outputs Accomplished

**Put on the slide:**

- Project scope, task assignments, architecture, and Sprint documentation prepared.
- Authentication completed with JWT, OTP/email verification, 2FA, password recovery, sessions, consent, and role-based access.
- Customer profile management completed for personal, business, and alternative information.
- Core loan workflow implemented: application, qualification, review, assignment, schedules, disbursement, and repayment.
- Document upload and review flow implemented, with S3-ready storage support and security validation.
- AI assistant, analytics dashboards, audit logging, and background processing implemented.
- Real-time notification foundation implemented through WebSockets, with final reliability and cross-platform behavior still being hardened.
- Team-reported web, backend, and mobile integration has reached approximately 80% core-feature completion.

**Suggested visual:** Three columns labeled Mobile Customer, Web Admin/Officer, and Backend Services. Use check marks for completed core outputs.

### Slide 4 — Demonstration and Evidence

**Put on the slide:**

- Account registration, OTP verification, login, and 2FA
- Customer profile creation and validation
- Loan application and officer review flow
- Document upload or review status
- Dashboard or analytics view
- Real-time notification example

**Use actual screenshots:**

1. Mobile login or customer profile screen
2. Mobile loan application or status screen
3. Web officer/admin dashboard
4. Notification received after a loan-related action
5. A small test-result screenshot, if readable

Do not attempt a long live demo inside a three-minute video. Show four or five screenshots with short captions instead.

### Slide 5 — Specific Contributors and Tasks

**Put on the slide:**

| Member | Specific Contribution Based on the Submitted Plan |
|---|---|
| Justin Mc Neal G. Caronongan | Managed scope, backlog, task assignments, progress tracking, staging coordination, integration testing, security testing, blockchain coordination, and defense planning. |
| Eli Gabriel T. Soriano | Set up the project, implemented remaining backend functions, supported S3 and blockchain enablement, fixed integration gaps, supported testing, tuned AI performance, and performed final backend hardening. |
| Joshua S. Co | Designed system and UI/UX flows, prepared diagrams and figures, reviewed web and mobile interfaces, checked blockchain-related presentation or verification needs, observed system flow, and prepared final interface polish. |
| John Lloyd Pimentel | Compiled Chapter 3 sources, supported Chapters 3 and 4, researched security and AI performance, finalized references, helped prepare the paper, and supported defense preparation. |
| Feniel A. Bartie | Prepared the manuscript, completed Chapter 3 documentation, drafted and finished Chapter 4, proofread the paper, drafted the defense script, checked the final manuscript, and assisted with final integration and submission. |

**Suggested visual:** Use one icon per role. Keep each contribution on the slide shorter than the table above; the speaker can explain the details.

### Slide 6 — Remaining Work and Next Milestone

**Put on the slide:**

- Complete loan, payment, disbursement, and repayment hardening.
- Finish notification reliability and cross-platform delivery checks.
- Run full web, backend, and mobile regression testing.
- Validate S3, blockchain, Redis/Celery, and production settings in an approved staging environment.
- Fix defects found during performance, security, and integration testing.
- Finish Chapter 4, manuscript formatting, defense slides, and final rehearsal.

**Closing line on the slide:**

> We have exceeded the 50% milestone, but the remaining 20% focuses on reliability, validation, and defense readiness.

## Timed Presentation Script

The following script is designed for five short speaking parts and should take about 2 minutes 45 seconds at a calm pace.

### Slide 1 — Justin, 0:00–0:25

“Good day. We are Group 6, and our project is MSME Pathways: Smart Loan Support for the Informal Sector. For this 50% milestone check, our team estimates that around 80% of the system’s core features are already implemented across the backend, web, and mobile applications. The remaining work is focused on hardening, testing, and deployment readiness.”

### Slide 2 — Justin, 0:25–0:50

“Our submitted timeline began with finalizing the project scope, backlog, roles, and deliverables. We then worked on document storage, Chapter 3, system architecture, and cross-platform integration. At the current checkpoint, we are conducting functional and security testing. Because implementation progressed ahead of the original schedule, some reliability and hardening activities have also started early.”

### Slide 3 — Eli, 0:50–1:25

“The completed backend outputs include secure authentication with OTP, two-factor authentication, password recovery, role permissions, and session handling. We also implemented customer profiles, document processing, AI assistance, analytics, audit logging, and the core loan process from application to repayment. WebSocket notifications are already implemented at the foundation level, while their final delivery behavior is still being hardened.”

### Slide 4 — Joshua, 1:25–1:50

“Our integration outputs connect the mobile customer flow, the web admin and loan-officer flow, and the backend services. The evidence shown includes registration and login, profile management, loan application and review, document handling, dashboards, and real-time notifications. We are continuing to polish the interfaces and verify that the same process remains consistent across platforms.”

### Slide 5 — John and Feniel, 1:50–2:25

**John:** “For research, I compiled sources for Chapters 3 and 4, reviewed security and AI performance topics, and checked the project references.”

**Feniel:** “For documentation, I prepared and proofread the manuscript, worked on Chapters 3 and 4, and helped draft the defense script and final submission materials. Our roles support both the technical system and the written project requirements.”

### Slide 6 — Justin, 2:25–2:50

“Next, we will finish loan and payment hardening, improve notification reliability, run complete cross-platform regression tests, and validate staging configurations. We will also finish Chapter 4 and prepare the final defense materials. In summary, the team has exceeded the required 50% milestone, while the remaining work will make the system stable, secure, and defense-ready. Thank you.”

## Individual Contribution Discussion and Point Allocation

This is a **recommended draft** based on the responsibilities written in the submitted PDF and the scope of each role. The team must discuss and approve the same final numbers before every member submits them.

| Member | Points | Justification |
|---|---:|---|
| Justin Mc Neal G. Caronongan | 30 | Led project management while also coordinating scope, integration, testing, staging, hardening, and defense preparation. The role covered both team coordination and technical validation. |
| Eli Gabriel T. Soriano | 25 | Held primary system-development responsibility, including remaining backend implementation, S3 and blockchain support, integration fixes, AI tuning, testing, and hardening. |
| Joshua S. Co | 20 | Led system design and UI/UX work, produced figures and flows, reviewed web and mobile behavior, supported integration, and performed interface polish. |
| John Lloyd Pimentel | 13 | Provided research support for the technical chapters, security and AI analysis, sources, references, paper finalization, and defense preparation. |
| Feniel A. Bartie | 12 | Prepared and organized the manuscript, completed and proofread chapters, drafted presentation material, and supported final checking and submission. |
| **Total** | **100** | The allocation does not exceed the required team total. |

### Contribution Discussion Checklist

Before submission, the team should:

1. Read each contribution aloud and allow the named member to correct missing work.
2. Agree on one point allocation totaling exactly 100.
3. Use the same member names, contributions, and points in every submission.
4. Keep screenshots, commits, documents, or task records as evidence if the faculty asks.
5. Revise the draft allocation if the team identifies additional work that changes the balance.

## Video and Slide Embedding Checklist

1. Record at 1080p if possible, using readable slides and clear audio.
2. Target 2:40–2:50; do not use the full three minutes during rehearsal.
3. Export the final recording as MP4.
4. Insert the MP4 into the required slide using the presentation app’s **Insert Video** option.
5. Set playback to start automatically or on click, depending on the professor’s instruction.
6. Test the embedded video on another device before submission.
7. Keep the video file and presentation in the same submission folder if the software links instead of fully embedding it.

## Evidence Available in the Backend Repository

- `README.md` lists implemented accounts, profiles, loans, documents, AI assistant, notifications, analytics, WebSockets, Redis, and Celery components.
- `docs/accounts/` and `docs/profiles/` contain testing and production-readiness reviews.
- `docs/LOANS_TESTING_GUIDE.md` and `docs/LOANS_PRODUCTION_READINESS_REVIEW.md` document the loan workflow and remaining hardening conditions.
- `docs/NOTIFICATIONS_TESTING_GUIDE.md` and `docs/NOTIFICATIONS_PRODUCTION_READINESS_REVIEW.md` document notification behavior and release checks.
- Existing automated tests cover authentication, profiles, loans, documents, AI, analytics, notifications, and WebSockets.

Do not show secrets, private customer data, uploaded documents, wallet keys, credentials, `.env` contents, or production logs in the presentation video.
