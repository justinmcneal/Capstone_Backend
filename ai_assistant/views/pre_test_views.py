import random

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.services.auth_service import AuthService
from accounts.utils.response_helpers import error_response, success_response


QUESTION_BANK = [
    {
        'id': 'PT001',
        'topic': 'interest_rates',
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'What does APR stand for in lending?',
        'options': [
            'Annual Payment Rate',
            'Annual Percentage Rate',
            'Average Principal Return',
            'Applied Premium Rate',
        ],
        'correct_answer': 'Annual Percentage Rate',
    },
    {
        'id': 'PT002',
        'topic': 'interest_rates',
        'type': 'true_false',
        'difficulty': 'medium',
        'question': 'Compound interest can increase the total amount repaid compared to simple interest.',
        'options': ['True', 'False'],
        'correct_answer': 'True',
    },
    {
        'id': 'PT003',
        'topic': 'loan_types',
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'Which loan type usually requires collateral?',
        'options': ['Secured loan', 'Unsecured loan', 'Credit card', 'Cash advance'],
        'correct_answer': 'Secured loan',
    },
    {
        'id': 'PT004',
        'topic': 'loan_types',
        'type': 'true_false',
        'difficulty': 'medium',
        'question': 'Unsecured loans often have higher rates because they are riskier for lenders.',
        'options': ['True', 'False'],
        'correct_answer': 'True',
    },
    {
        'id': 'PT005',
        'topic': 'debt_management',
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'What does debt-to-income ratio compare?',
        'options': [
            'Assets vs liabilities',
            'Monthly debt payments vs monthly income',
            'Revenue vs expenses',
            'Income vs savings',
        ],
        'correct_answer': 'Monthly debt payments vs monthly income',
    },
    {
        'id': 'PT006',
        'topic': 'debt_management',
        'type': 'multiple_choice',
        'difficulty': 'hard',
        'question': 'Which strategy usually minimizes interest over time?',
        'options': [
            'Pay highest-interest debt first',
            'Pay lowest balance first',
            'Pause all debt payments',
            'Pay only minimum forever',
        ],
        'correct_answer': 'Pay highest-interest debt first',
    },
    {
        'id': 'PT007',
        'topic': 'budgeting_basics',
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'In a basic budget, net cash flow is:',
        'options': [
            'Revenue minus expenses',
            'Expenses minus revenue',
            'Revenue plus debt',
            'Savings minus taxes',
        ],
        'correct_answer': 'Revenue minus expenses',
    },
    {
        'id': 'PT008',
        'topic': 'budgeting_basics',
        'type': 'true_false',
        'difficulty': 'medium',
        'question': 'A budget should be reviewed regularly, not just once per year.',
        'options': ['True', 'False'],
        'correct_answer': 'True',
    },
    {
        'id': 'PT009',
        'topic': 'repayment_concepts',
        'type': 'multiple_choice',
        'difficulty': 'easy',
        'question': 'An amortized monthly payment usually includes:',
        'options': ['Interest only', 'Principal only', 'Principal and interest', 'Fees only'],
        'correct_answer': 'Principal and interest',
    },
    {
        'id': 'PT010',
        'topic': 'repayment_concepts',
        'type': 'true_false',
        'difficulty': 'easy',
        'question': 'Late payments may increase total repayment cost through penalties.',
        'options': ['True', 'False'],
        'correct_answer': 'True',
    },
    {
        'id': 'PT011',
        'topic': 'interest_rates',
        'type': 'multiple_choice',
        'difficulty': 'medium',
        'question': 'A lender offers 2% monthly nominal rate. Approximate annual nominal rate is:',
        'options': ['12%', '18%', '24%', '36%'],
        'correct_answer': '24%',
    },
    {
        'id': 'PT012',
        'topic': 'loan_types',
        'type': 'multiple_choice',
        'difficulty': 'medium',
        'question': 'Which product is best described as revolving credit?',
        'options': [
            'Fixed 12-month installment loan',
            'Reusable credit line as balance is repaid',
            'One-time grant',
            'Insurance contract',
        ],
        'correct_answer': 'Reusable credit line as balance is repaid',
    },
    {
        'id': 'PT013',
        'topic': 'debt_management',
        'type': 'true_false',
        'difficulty': 'easy',
        'question': 'Missing debt payments can hurt creditworthiness.',
        'options': ['True', 'False'],
        'correct_answer': 'True',
    },
    {
        'id': 'PT014',
        'topic': 'budgeting_basics',
        'type': 'multiple_choice',
        'difficulty': 'medium',
        'question': 'Which practice improves budget reliability?',
        'options': [
            'Ignoring irregular expenses',
            'Including a contingency amount',
            'Assuming best-case sales only',
            'Skipping debt payments in plan',
        ],
        'correct_answer': 'Including a contingency amount',
    },
    {
        'id': 'PT015',
        'topic': 'repayment_concepts',
        'type': 'multiple_choice',
        'difficulty': 'hard',
        'question': 'Longer loan terms usually lead to:',
        'options': [
            'Higher monthly payment and lower total interest',
            'Lower monthly payment but potentially higher total interest',
            'No change in repayment profile',
            'Instant principal reduction',
        ],
        'correct_answer': 'Lower monthly payment but potentially higher total interest',
    },
]


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

        try:
            raw_count = request.query_params.get('count', '10')
            count = int(raw_count)
        except ValueError:
            return error_response(
                message='count must be an integer',
                errors={'count': 'Invalid integer value'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        count = max(1, min(count, len(QUESTION_BANK)))
        selected = random.sample(QUESTION_BANK, k=count)

        sanitized_questions = [
            {
                'id': q['id'],
                'topic': q['topic'],
                'type': q['type'],
                'difficulty': q['difficulty'],
                'question': q['question'],
                'options': q['options'],
            }
            for q in selected
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
            'budgeting_basics': 'budgeting',
            'debt_management': 'debt_credit',
            'loan_types': 'loan_basics',
            'interest_rates': 'loan_basics',
            'repayment_concepts': 'debt_credit',
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

        lookup = {q['id']: q for q in QUESTION_BANK}
        total_questions = 0
        correct_answers = 0
        missed_topic_counts = {}

        for question_id, selected_answer in answers.items():
            question = lookup.get(str(question_id))
            if question is None:
                continue

            total_questions += 1
            expected = str(question['correct_answer']).strip().lower()
            actual = str(selected_answer).strip().lower()
            if expected == actual:
                correct_answers += 1
            else:
                topic = str(question.get('topic') or '').strip().lower()
                if topic:
                    missed_topic_counts[topic] = missed_topic_counts.get(topic, 0) + 1

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

        if customer:
            customer.has_taken_pretest = True
            customer.pretest_score = correct_answers
            customer.pretest_total_questions = total_questions
            customer.pretest_percentage = percentage
            customer.pretest_completed_at = completed_at
            customer.pretest_weak_areas = weak_areas
            if not isinstance(getattr(customer, 'learn_module_progress', None), dict):
                customer.learn_module_progress = {}
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
            },
            message='Pre-test submitted successfully',
        )
