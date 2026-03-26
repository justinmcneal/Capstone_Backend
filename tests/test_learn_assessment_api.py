from types import SimpleNamespace
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from ai_assistant.views.pre_test_views import (
    POST_TEST_QUESTION_BANK,
    POST_TEST_TOPICS,
    PRE_TEST_QUESTION_BANK,
    PostTestSubmitView,
    PreTestQuestionsView,
    PreTestSubmitView,
)


class DummyCustomer:
    def __init__(
        self,
        has_taken_pretest=False,
        learn_module_progress=None,
    ):
        self.has_taken_pretest = has_taken_pretest
        self.learn_module_progress = (
            learn_module_progress if learn_module_progress is not None else {}
        )
        self.pretest_score = None
        self.pretest_total_questions = None
        self.pretest_percentage = None
        self.pretest_completed_at = None
        self.pretest_weak_areas = []
        self.saved = False

    def save(self):
        self.saved = True


def _authed_request(method, path, payload=None):
    factory = APIRequestFactory()
    if method == 'GET':
        request = factory.get(path)
    else:
        request = factory.post(path, payload or {}, format='json')
    force_authenticate(request, user=SimpleNamespace(customer_id='test-customer-id'))
    return request


def _pick_wrong_answer(question):
    for option in question['options']:
        if str(option).strip().lower() != str(question['correct_answer']).strip().lower():
            return option
    return question['options'][0]


@patch('ai_assistant.views.pre_test_views.AuthService.get_customer_by_id')
def test_pre_test_questions_are_deterministic_and_aligned(mock_get_customer):
    mock_get_customer.return_value = DummyCustomer(has_taken_pretest=False)

    request = _authed_request('GET', '/learn/pre-test/questions/')
    response = PreTestQuestionsView.as_view()(request)

    assert response.status_code == status.HTTP_200_OK
    data = response.data['data']
    questions = data['questions']

    assert data['total_questions'] == 10
    assert len(questions) == len(PRE_TEST_QUESTION_BANK)
    assert [q['id'] for q in questions] == [q['id'] for q in PRE_TEST_QUESTION_BANK]
    assert [q['topic'] for q in questions] == POST_TEST_TOPICS


@patch('ai_assistant.views.pre_test_views.AuthService.get_customer_by_id')
def test_pre_test_submit_returns_10_item_topic_baseline(mock_get_customer):
    customer = DummyCustomer(has_taken_pretest=False, learn_module_progress={})
    mock_get_customer.return_value = customer

    answers = {
        q['id']: q['correct_answer']
        for q in PRE_TEST_QUESTION_BANK
    }
    # Force one wrong answer so boolean flags can be validated.
    answers['PRE005'] = _pick_wrong_answer(PRE_TEST_QUESTION_BANK[4])

    request = _authed_request('POST', '/learn/pre-test/submit/', {'answers': answers})
    response = PreTestSubmitView.as_view()(request)

    assert response.status_code == status.HTTP_200_OK
    data = response.data['data']
    baseline = data['pre_test_topic_results']

    assert len(baseline) == 10
    assert all(isinstance(item, bool) for item in baseline)
    assert baseline[4] is False
    assert customer.learn_module_progress['pre_test_topic_results'] == baseline
    assert customer.saved is True


@patch('ai_assistant.views.pre_test_views.AuthService.get_customer_by_id')
def test_post_test_submit_rejects_duplicate_submission(mock_get_customer):
    customer = DummyCustomer(
        has_taken_pretest=True,
        learn_module_progress={'post_test': {'post_test_score': 8}},
    )
    mock_get_customer.return_value = customer

    payload = {
        'user_name': 'Test User',
        'pre_test_score': 6,
        'pre_test_topic_results': [True] * 10,
        'answers': [q['correct_index'] for q in POST_TEST_QUESTION_BANK],
    }

    request = _authed_request('POST', '/learn/post-test/submit/', payload)
    response = PostTestSubmitView.as_view()(request)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data['message'] == 'Post-test already completed'


@patch('ai_assistant.views.pre_test_views.AuthService.get_customer_by_id')
def test_post_test_submit_returns_recommended_next_actions(mock_get_customer):
    customer = DummyCustomer(has_taken_pretest=True, learn_module_progress={})
    mock_get_customer.return_value = customer

    # Intentionally wrong answers produce weak topics and non-empty next actions.
    payload = {
        'user_name': 'Test User',
        'pre_test_score': 3,
        'pre_test_topic_results': [False] * 10,
        'answers': [0] * 10,
    }

    request = _authed_request('POST', '/learn/post-test/submit/', payload)
    response = PostTestSubmitView.as_view()(request)

    assert response.status_code == status.HTTP_200_OK
    data = response.data['data']
    assert 'next_actions' in data
    assert isinstance(data['next_actions'], list)
    assert len(data['next_actions']) >= 1
