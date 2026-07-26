from ai_assistant.views.chat import ChatView
from ai_assistant.views.streaming import StreamingChatView
from ai_assistant.views.history import ChatHistoryView
from ai_assistant.views.auxiliary import (
    SuggestionsView,
    AIStatusView,
    EducationView,
    FAQsView,
)

__all__ = [
    'ChatView',
    'StreamingChatView',
    'ChatHistoryView',
    'SuggestionsView',
    'AIStatusView',
    'EducationView',
    'FAQsView',
]
