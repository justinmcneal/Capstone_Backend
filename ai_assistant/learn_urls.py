from django.urls import path

from ai_assistant.views.pre_test_views import PreTestQuestionsView, PreTestSubmitView

app_name = 'learn'

urlpatterns = [
    path('pre-test/questions/', PreTestQuestionsView.as_view(), name='pre-test-questions'),
    path('pre-test/submit/', PreTestSubmitView.as_view(), name='pre-test-submit'),
]
