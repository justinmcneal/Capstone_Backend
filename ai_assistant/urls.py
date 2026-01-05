from django.urls import path
from ai_assistant.views import (
    ChatView,
    ChatHistoryView,
    SuggestionsView,
    AIStatusView
)

app_name = 'ai_assistant'

urlpatterns = [
    # Main chat endpoint
    path('chat/', ChatView.as_view(), name='chat'),
    
    # Chat history
    path('history/', ChatHistoryView.as_view(), name='history'),
    
    # Conversation starters
    path('suggestions/', SuggestionsView.as_view(), name='suggestions'),
    
    # AI service status
    path('status/', AIStatusView.as_view(), name='status'),
]
