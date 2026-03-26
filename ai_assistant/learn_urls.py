from django.urls import path

from ai_assistant.views.pre_test_views import (
    PostTestQuestionsView,
    PostTestSubmitView,
    PreTestQuestionsView,
    PreTestSubmitView,
)

app_name = 'learn'

urlpatterns = [
    path('pre-test/questions/', PreTestQuestionsView.as_view(), name='pre-test-questions'),
    path('pre-test/submit/', PreTestSubmitView.as_view(), name='pre-test-submit'),
    path('post-test/questions/', PostTestQuestionsView.as_view(), name='post-test-questions'),
    path('post-test/submit/', PostTestSubmitView.as_view(), name='post-test-submit'),
]
