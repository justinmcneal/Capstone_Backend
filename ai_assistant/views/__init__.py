from ai_assistant.views.auxiliary import (
    AIStatusView,
    EducationView,
    FAQsView,
    SuggestionsView,
)
from ai_assistant.views.chat import ChatView
from ai_assistant.views.history import ChatHistoryView
from ai_assistant.views.officer import (
    OfficerAIStatusView,
    OfficerChatView,
    OfficerStreamingChatView,
    OfficerSuggestionsView,
)
from ai_assistant.views.streaming import StreamingChatView

__all__ = [
    'AIStatusView',
    'ChatHistoryView',
    'ChatView',
    'EducationView',
    'FAQsView',
    'OfficerAIStatusView',
    'OfficerChatView',
    'OfficerStreamingChatView',
    'OfficerSuggestionsView',
    'StreamingChatView',
    'SuggestionsView',
]
