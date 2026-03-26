from django.urls import path
from ai_assistant.views import (
    ChatView,
    StreamingChatView,
    ChatHistoryView,
    SuggestionsView,
    AIStatusView,
    EducationView,
    ModuleProgressView,
    FAQsView
)

app_name = 'ai_assistant'

urlpatterns = [
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
    path('education/progress/', ModuleProgressView.as_view(), name='education-progress'),
    path('education/<str:topic>/', EducationView.as_view(), name='education-topic'),
    
    # FAQs
    path('faqs/', FAQsView.as_view(), name='faqs'),
]
