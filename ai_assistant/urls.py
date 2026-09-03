from django.urls import path

from ai_assistant.views import (
    AIStatusView,
    ChatHistoryView,
    ChatView,
    EducationView,
    FAQsView,
    OfficerAIStatusView,
    OfficerChatView,
    OfficerFeedbackView,
    OfficerStreamingChatView,
    OfficerSuggestionsView,
    StreamingChatView,
    SuggestionsView,
)

app_name = 'ai_assistant'

urlpatterns = [
    path('officer/status/', OfficerAIStatusView.as_view(), name='officer-status'),
    path('officer/suggestions/', OfficerSuggestionsView.as_view(), name='officer-suggestions'),
    path('officer/chat/', OfficerChatView.as_view(), name='officer-chat'),
    path('officer/chat/stream/', OfficerStreamingChatView.as_view(), name='officer-chat-stream'),
    path('officer/feedback/', OfficerFeedbackView.as_view(), name='officer-feedback'),

    # Main chat endpoint
    path('chat/', ChatView.as_view(), name='chat'),
    
    # Streaming chat endpoint (SSE)
    path('chat/stream/', StreamingChatView.as_view(), name='chat-stream'),
    
    # Chat history
    path('history/', ChatHistoryView.as_view(), name='history'),
    
    # Conversation starters
    path('suggestions/', SuggestionsView.as_view(), name='suggestions'),
    
    # AI service status
    path('status/', AIStatusView.as_view(), name='status'),
    
    # Education content
    path('education/', EducationView.as_view(), name='education'),
    path('education/<str:topic>/', EducationView.as_view(), name='education-topic'),
    
    # FAQs
    path('faqs/', FAQsView.as_view(), name='faqs'),
]
