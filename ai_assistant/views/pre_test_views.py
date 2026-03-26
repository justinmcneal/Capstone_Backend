from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.services.auth_service import AuthService
from accounts.utils.response_helpers import error_response, success_response


POST_TEST_TOPICS = [
    'Budgeting basics',
    'Cash flow management',
    'Separating personal vs. business funds',
    'Understanding loans and interest',
    'Emergency savings behavior',
    'Profit vs. revenue distinction',
    'Credit readiness awareness',
    'Record-keeping habits',
    'Financial goal-setting',
    'Loan readiness self-assessment',
]


PRE_TEST_QUESTION_BANK = [
    {
        'id': 'PRE001',
        'topic': POST_TEST_TOPICS[0],
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'A sari-sari store earns P2,000 in one day and spends P1,300. What is left as available budget for that day?',
        'options': ['P700', 'P500', 'P900', 'P300'],
        'correct_answer': 'P700',
    },
    {
        'id': 'PRE002',
        'topic': POST_TEST_TOPICS[1],
        'type': 'true_false',
        'difficulty': 'easy',
        'question': 'If your weekly cash out is higher than cash in, your business has negative cash flow.',
        'options': ['True', 'False'],
        'correct_answer': 'True',
    },
    {
        'id': 'PRE003',
        'topic': POST_TEST_TOPICS[2],
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'What is the best way to separate personal and business money?',
        'options': [
            'Use one wallet for everything',
            'Track only big expenses',
            'Use a separate account or envelope for business',
            'Record only income',
        ],
        'correct_answer': 'Use a separate account or envelope for business',
    },
    {
        'id': 'PRE004',
        'topic': POST_TEST_TOPICS[3],
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'You borrow P10,000 at 10% simple annual interest for one year. About how much do you repay?',
        'options': ['P10,100', 'P10,500', 'P11,000', 'P12,000'],
        'correct_answer': 'P11,000',
    },
    {
        'id': 'PRE005',
        'topic': POST_TEST_TOPICS[4],
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'Which is a healthy emergency savings habit for microbusiness owners?',
        'options': [
            'Save only when income is very high',
            'Set aside a small fixed amount regularly',
            'Use all savings for non-essential spending',
            'Wait for emergencies before saving',
        ],
        'correct_answer': 'Set aside a small fixed amount regularly',
    },
    {
        'id': 'PRE006',
        'topic': POST_TEST_TOPICS[5],
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'Sales are P3,500 and product costs are P2,200. What is gross profit?',
        'options': ['P1,300', 'P2,200', 'P3,500', 'P5,700'],
        'correct_answer': 'P1,300',
    },
    {
        'id': 'PRE007',
        'topic': POST_TEST_TOPICS[6],
        'type': 'multiple_choice',
        'difficulty': 'medium',
        'question': 'Which action improves credit readiness before loan application?',
        'options': [
            'Ignore due dates during slow weeks',
            'Pay on time and keep repayment records',
            'Hide existing debts on forms',
            'Borrow from multiple lenders at once',
        ],
        'correct_answer': 'Pay on time and keep repayment records',
    },
    {
        'id': 'PRE008',
        'topic': POST_TEST_TOPICS[7],
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'Which daily record helps most for financial tracking?',
        'options': [
            'Only weekly memory notes',
            'Daily sales and expense log',
            'Only monthly sales total',
            'Customer names only',
        ],
        'correct_answer': 'Daily sales and expense log',
    },
    {
        'id': 'PRE009',
        'topic': POST_TEST_TOPICS[8],
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'Which is a clear financial goal?',
        'options': [
            'I want more income soon',
            'Save P500 monthly for 6 months for inventory',
            'Avoid all expenses forever',
            'Sell more somehow',
        ],
        'correct_answer': 'Save P500 monthly for 6 months for inventory',
    },
    {
        'id': 'PRE010',
        'topic': POST_TEST_TOPICS[9],
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'Before taking a loan, what should be checked first?',
        'options': [
            'If your expected cash flow can repay it',
            'If it is the biggest loan amount',
            'If friends are also borrowing',
            'If approval is fastest regardless of terms',
        ],
        'correct_answer': 'If your expected cash flow can repay it',
    },
]


POST_TEST_QUESTION_BANK = [
    {
        'id': 'POST001',
        'topic': POST_TEST_TOPICS[0],
        'question': 'Your tindahan earns P2,500 today. You spent P1,600 on stock and P400 on transport. What is your remaining budget for other needs today?',
        'choices': ['P500', 'P700', 'P900', 'P1,300'],
        'correct_index': 0,
    },
    {
        'id': 'POST002',
        'topic': POST_TEST_TOPICS[1],
        'question': 'A palengke vendor had P3,000 cash in and P3,400 cash out this week. What does this mean?',
        'choices': [
            'Positive cash flow of P400',
            'Negative cash flow of P400',
            'Break-even cash flow',
            'Profit of P3,400',
        ],
        'correct_index': 1,
    },
    {
        'id': 'POST003',
        'topic': POST_TEST_TOPICS[2],
        'question': 'Which action best separates personal and business funds for a freelancer?',
        'choices': [
            'Use one wallet for all spending',
            'Track only large expenses',
            'Keep a separate business account or envelope',
            'Borrow from business cash without recording',
        ],
        'correct_index': 2,
    },
    {
        'id': 'POST004',
        'topic': POST_TEST_TOPICS[3],
        'question': 'You borrow P10,000 with 10% annual interest for one year. About how much total do you repay?',
        'choices': ['P10,100', 'P10,500', 'P11,000', 'P12,000'],
        'correct_index': 2,
    },
    {
        'id': 'POST005',
        'topic': POST_TEST_TOPICS[4],
        'question': 'What is a healthy emergency savings habit for a small store owner?',
        'choices': [
            'Save only when business is very strong',
            'Set aside a fixed small amount every week',
            'Use all savings to buy non-essential items',
            'Wait for an emergency before planning savings',
        ],
        'correct_index': 1,
    },
    {
        'id': 'POST006',
        'topic': POST_TEST_TOPICS[5],
        'question': 'Your daily sales are P4,000 and product costs are P2,800. What is your gross profit for the day?',
        'choices': ['P1,200', 'P2,800', 'P4,000', 'P6,800'],
        'correct_index': 0,
    },
    {
        'id': 'POST007',
        'topic': POST_TEST_TOPICS[6],
        'question': 'Which behavior improves your credit readiness before applying for a loan?',
        'choices': [
            'Skipping due dates when sales are low',
            'Keeping repayment records and paying on time',
            'Applying to many lenders on the same day',
            'Hiding existing debts from lender forms',
        ],
        'correct_index': 1,
    },
    {
        'id': 'POST008',
        'topic': POST_TEST_TOPICS[7],
        'question': 'What is the most useful daily record for a sari-sari store?',
        'choices': [
            'Only total monthly sales',
            'A list of daily sales and daily expenses',
            'Only unpaid customer utang',
            'A weekly memory-based estimate',
        ],
        'correct_index': 1,
    },
    {
        'id': 'POST009',
        'topic': POST_TEST_TOPICS[8],
        'question': 'Which goal is best written as a clear financial goal?',
        'choices': [
            'I want more money soon',
            'I will save P500 monthly for 6 months for business inventory',
            'I hope sales always go up',
            'I will avoid all expenses forever',
        ],
        'correct_index': 1,
    },
    {
        'id': 'POST010',
        'topic': POST_TEST_TOPICS[9],
        'question': 'Before taking a business loan, what should you check first?',
        'choices': [
            'If friends also want a loan',
            'If you can repay from expected cash flow after expenses',
            'If the loan has the biggest amount available',
            'If approval is fastest even with unclear terms',
        ],
        'correct_index': 1,
    },
]


def _topic_names_from_flags(flags):
    return [
        topic
        for index, topic in enumerate(POST_TEST_TOPICS)
        if index < len(flags) and not bool(flags[index])
    ]


def _build_feedback_message(user_name, post_test_score, growth_delta, weak_topics):
    name = (str(user_name or '').strip() or 'Learner')
    delta_word = f"+{growth_delta}" if growth_delta >= 0 else str(growth_delta)

    first_sentence = (
        f"{name}, your post-test score is {post_test_score}/10, which is {delta_word} compared with your pre-test."
    )

    if weak_topics:
        focus_topics = ', '.join(weak_topics[:2])
        second_sentence = (
            f"Keep improving by practicing {focus_topics} using daily business records and simple weekly reviews."
        )
    else:
        second_sentence = (
            'Strong job on all topics, so continue your weekly habits to keep your loan readiness high.'
        )

    return f"{first_sentence} {second_sentence}"


def _build_next_actions(weak_topics):
    action_by_topic = {
        'Budgeting basics': 'Create a 7-day budget sheet and record daily cash in/out before closing.',
        'Cash flow management': 'Track weekly inflow versus outflow and adjust purchases to avoid negative cash flow.',
        'Separating personal vs. business funds': 'Start using a separate envelope or account for business transactions this week.',
        'Understanding loans and interest': 'Review one sample loan offer and compute total repayment before deciding.',
        'Emergency savings behavior': 'Set an automatic weekly emergency savings amount, even if it is small.',
        'Profit vs. revenue distinction': 'Compute daily profit as sales minus product cost and record it beside revenue.',
        'Credit readiness awareness': 'Pay obligations on schedule and keep proof of payment in one folder.',
        'Record-keeping habits': 'Maintain a daily log for sales, expenses, and receivables.',
        'Financial goal-setting': 'Write one SMART financial goal with amount, timeline, and weekly target.',
        'Loan readiness self-assessment': 'Use a simple monthly cash flow check before any new loan application.',
    }

    if not weak_topics:
        return [
            'Keep your current weekly finance routine and review your records every Sunday.',
            'Prepare the latest 4 weeks of business records to stay loan-ready.',
        ]

    actions = []
    for topic in weak_topics:
        action = action_by_topic.get(topic)
        if action and action not in actions:
            actions.append(action)
        if len(actions) >= 3:
            break

    if len(actions) < 3:
        fallback_actions = [
            'Review your weakest topic module and retake practice questions this week.',
            'Ask your loan officer or mentor to review your financial records for gaps.',
        ]
        for fallback in fallback_actions:
            if fallback not in actions:
                actions.append(fallback)
            if len(actions) >= 3:
                break

    return actions


class PreTestQuestionsView(APIView):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        customer = AuthService.get_customer_by_id(request.user.customer_id)
        if customer and getattr(customer, 'has_taken_pretest', False):
            return error_response(
                message='Pre-test already completed',
                errors={'pre_test': 'This assessment can only be taken once'},
                status_code=status.HTTP_409_CONFLICT,
            )

        sanitized_questions = [
            {
                'id': q['id'],
                'topic': q['topic'],
                'type': q['type'],
                'difficulty': q['difficulty'],
                'question': q['question'],
                'options': q['options'],
            }
            for q in PRE_TEST_QUESTION_BANK
        ]

        return success_response(
            data={
                'questions': sanitized_questions,
                'total_questions': len(sanitized_questions),
            },
            message='Pre-test questions loaded successfully',
        )


class PreTestSubmitView(APIView):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        weak_area_by_topic = {
            'budgeting basics': 'budgeting',
            'cash flow management': 'budgeting',
            'separating personal vs. business funds': 'budgeting',
            'understanding loans and interest': 'loan_basics',
            'emergency savings behavior': 'budgeting',
            'profit vs. revenue distinction': 'budgeting',
            'credit readiness awareness': 'debt_credit',
            'record-keeping habits': 'budgeting',
            'financial goal-setting': 'budgeting',
            'loan readiness self-assessment': 'debt_credit',
        }

        customer = AuthService.get_customer_by_id(request.user.customer_id)
        if customer and getattr(customer, 'has_taken_pretest', False):
            return error_response(
                message='Pre-test already completed',
                errors={'pre_test': 'This assessment can only be submitted once'},
                status_code=status.HTTP_409_CONFLICT,
            )

        answers = request.data.get('answers')

        if not isinstance(answers, dict) or not answers:
            return error_response(
                message='answers must be a non-empty object',
                errors={'answers': 'Expected map of question_id to answer'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        lookup = {q['id']: q for q in PRE_TEST_QUESTION_BANK}
        total_questions = 0
        correct_answers = 0
        missed_topic_counts = {}
        topic_result_lookup = {}

        for question_id, selected_answer in answers.items():
            question = lookup.get(str(question_id))
            if question is None:
                continue

            total_questions += 1
            expected = str(question['correct_answer']).strip().lower()
            actual = str(selected_answer).strip().lower()
            normalized_topic = str(question.get('topic') or '').strip().lower()

            if expected == actual:
                correct_answers += 1
                if normalized_topic:
                    topic_result_lookup[normalized_topic] = True
            else:
                if normalized_topic:
                    topic_result_lookup[normalized_topic] = False
                    missed_topic_counts[normalized_topic] = (
                        missed_topic_counts.get(normalized_topic, 0) + 1
                    )

        if total_questions == 0:
            return error_response(
                message='No valid question ids were submitted',
                errors={'answers': 'Submitted ids do not match the question bank'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        percentage = round((correct_answers / total_questions) * 100, 2)
        completed_at = timezone.now()
        ordered_missed_topics = [
            topic
            for topic, _ in sorted(
                missed_topic_counts.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ]

        weak_areas = []
        for topic in ordered_missed_topics:
            mapped = weak_area_by_topic.get(topic)
            if mapped and mapped not in weak_areas:
                weak_areas.append(mapped)

        pre_test_topic_results = [
            bool(topic_result_lookup.get(topic.lower(), False))
            for topic in POST_TEST_TOPICS
        ]

        if customer:
            customer.has_taken_pretest = True
            customer.pretest_score = correct_answers
            customer.pretest_total_questions = total_questions
            customer.pretest_percentage = percentage
            customer.pretest_completed_at = completed_at
            customer.pretest_weak_areas = weak_areas
            if not isinstance(getattr(customer, 'learn_module_progress', None), dict):
                customer.learn_module_progress = {}
            customer.learn_module_progress['pre_test_topic_results'] = pre_test_topic_results
            customer.save()

        return success_response(
            data={
                'score': correct_answers,
                'correct_answers': correct_answers,
                'total_questions': total_questions,
                'percentage': percentage,
                'completed_at': completed_at.isoformat(),
                'has_taken_pretest': True,
                'weak_areas': weak_areas,
                'pre_test_topic_results': pre_test_topic_results,
            },
            message='Pre-test submitted successfully',
        )


class PostTestQuestionsView(APIView):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sanitized_questions = [
            {
                'id': q['id'],
                'topic': q['topic'],
                'question': q['question'],
                'choices': q['choices'],
            }
            for q in POST_TEST_QUESTION_BANK
        ]

        return success_response(
            data={
                'questions': sanitized_questions,
                'total_questions': len(sanitized_questions),
            },
            message='Post-test questions loaded successfully',
        )


class PostTestSubmitView(APIView):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        customer = AuthService.get_customer_by_id(request.user.customer_id)
        if customer and isinstance(getattr(customer, 'learn_module_progress', None), dict):
            existing_post_test = customer.learn_module_progress.get('post_test')
            if isinstance(existing_post_test, dict) and existing_post_test:
                return error_response(
                    message='Post-test already completed',
                    errors={'post_test': 'This assessment can only be submitted once'},
                    status_code=status.HTTP_409_CONFLICT,
                )

        user_name = request.data.get('user_name')
        raw_pre_test_score = request.data.get('pre_test_score')
        pre_test_topic_results = request.data.get('pre_test_topic_results')
        answers = request.data.get('answers')

        if not isinstance(raw_pre_test_score, (int, float)):
            return error_response(
                message='pre_test_score must be a number from 0 to 10',
                errors={'pre_test_score': 'Expected numeric score'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        pre_test_score = int(raw_pre_test_score)
        if pre_test_score < 0 or pre_test_score > 10:
            return error_response(
                message='pre_test_score must be between 0 and 10',
                errors={'pre_test_score': 'Out of allowed range'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if (
            not isinstance(pre_test_topic_results, list)
            or len(pre_test_topic_results) != len(POST_TEST_TOPICS)
            or not all(isinstance(v, bool) for v in pre_test_topic_results)
        ):
            return error_response(
                message='pre_test_topic_results must be a 10-item boolean array',
                errors={'pre_test_topic_results': 'Expected [true/false x10]'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(answers, list) or len(answers) != len(POST_TEST_QUESTION_BANK):
            return error_response(
                message='answers must be a 10-item array of choice indexes',
                errors={'answers': 'Expected [0-3 x10]'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        topic_results = []
        for index, selected_index in enumerate(answers):
            if not isinstance(selected_index, int) or selected_index < 0 or selected_index > 3:
                return error_response(
                    message='Each answer must be an integer from 0 to 3',
                    errors={'answers': f'Invalid answer index at position {index}'},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            correct_index = int(POST_TEST_QUESTION_BANK[index]['correct_index'])
            topic_results.append(selected_index == correct_index)

        post_test_score = sum(1 for item in topic_results if item)
        growth_delta = post_test_score - pre_test_score
        weak_topics = _topic_names_from_flags(topic_results)
        improved_topics = [
            POST_TEST_TOPICS[index]
            for index in range(len(POST_TEST_TOPICS))
            if (not pre_test_topic_results[index]) and topic_results[index]
        ]
        feedback_message = _build_feedback_message(
            user_name=user_name,
            post_test_score=post_test_score,
            growth_delta=growth_delta,
            weak_topics=weak_topics,
        )
        next_actions = _build_next_actions(weak_topics)
        loan_readiness_passed = post_test_score >= 7

        if customer:
            if not isinstance(getattr(customer, 'learn_module_progress', None), dict):
                customer.learn_module_progress = {}

            customer.learn_module_progress['post_test'] = {
                'post_test_score': post_test_score,
                'growth_delta': growth_delta,
                'topic_results': topic_results,
                'weak_topics': weak_topics,
                'improved_topics': improved_topics,
                'next_actions': next_actions,
                'loan_readiness_passed': loan_readiness_passed,
                'completed_at': timezone.now().isoformat(),
            }
            customer.save()

        return success_response(
            data={
                'post_test_score': post_test_score,
                'growth_delta': growth_delta,
                'topic_results': topic_results,
                'weak_topics': weak_topics,
                'improved_topics': improved_topics,
                'feedback_message': feedback_message,
                'next_actions': next_actions,
                'loan_readiness_passed': loan_readiness_passed,
            },
            message='Post-test submitted successfully',
        )
