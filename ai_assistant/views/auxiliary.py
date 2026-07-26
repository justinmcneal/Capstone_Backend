from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.throttles import ChatRateThrottle
from accounts.utils.validation_utils import sanitize_text
from accounts.services.consent_service import ConsentService
from ai_assistant.services import get_llm_service
from ai_assistant.views.chat_views import ConsentRequiredMixin, CACHE_TTL
from django.core.cache import cache
import logging

logger = logging.getLogger('ai_assistant')


class SuggestionsView(ConsentRequiredMixin, APIView):
    """
    Get conversation starters/suggestions.
    
    GET /api/ai/suggestions/
    
    Responses are cached per language for performance.
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    ALLOWED_LANGUAGES = {'en', 'tl'}
    
    def get(self, request):
        """Get conversation starters"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result

        user = request.user
        requested_language = sanitize_text(
            request.query_params.get('language', user.language if hasattr(user, 'language') else 'en')
        ).lower()
        if requested_language not in self.ALLOWED_LANGUAGES:
            return error_response(
                message="Invalid language value",
                errors={'language': f"language must be one of: {', '.join(sorted(self.ALLOWED_LANGUAGES))}"},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        language = requested_language
        
        cache_key = f'ai_suggestions_{language}'
        cached_data = cache.get(cache_key)
        if cached_data:
            return success_response(
                data={'suggestions': cached_data, 'language': language, 'cached': True},
                message="Suggestions retrieved successfully"
            )
        
        if language == 'tl':
            suggestions = [
                "Ano ang loan at paano ito gumagana?",
                "Paano mag-apply ng loan para sa maliit na negosyo?",
                "Ano-ano ang mga requirements para sa loan?",
                "Magkano ang pwede kong i-loan?",
                "Paano malalaman kung approved ang loan ko?",
                "Paano magbayad ng loan?",
                "Ano-ano ang mga paraan ng pagbabayad?",
                "Paano gumagana ang blockchain verification?",
            ]
        else:
            suggestions = [
                "What is a loan and how does it work?",
                "How do I apply for a small business loan?",
                "What documents do I need for a loan?",
                "How much can I borrow?",
                "How will I know if my loan is approved?",
                "How do I make a payment?",
                "What payment methods are available?",
                "How does blockchain verification work?",
            ]
        
        cache.set(cache_key, suggestions, CACHE_TTL.get('suggestions', 43200))
        
        return success_response(
            data={'suggestions': suggestions, 'language': language, 'cached': False},
            message="Suggestions retrieved successfully"
        )


class AIStatusView(AccessControlMixin, APIView):
    """
    Check AI service status.
    
    GET /api/ai/status/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Check if AI service is available"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result

        llm = get_llm_service(use_case='chat')
        
        is_available = llm.is_available()
        
        return success_response(
            data={
                'available': is_available,
                'provider': llm.provider,
                'current_model': llm.model if is_available else None,
                'api_configured': bool(llm.api_key)
            },
            message="AI status retrieved"
        )


class EducationView(AccessControlMixin, APIView):
    """
    Get loan education content.
    
    GET /api/ai/education/
    GET /api/ai/education/<topic>/
    
    Responses are cached for performance (content rarely changes).
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    TOPICS = {
        'what_is_a_loan': {
            'title': 'What is a Loan?',
            'content': 'A loan is money you borrow and agree to pay back with interest. Think of it as a tool to help your business grow when you need funds.',
            'key_points': [
                'You receive money upfront',
                'You pay it back in installments',
                'Interest is the cost of borrowing'
            ]
        },
        'interest_rates': {
            'title': 'Understanding Interest Rates',
            'content': 'Interest is what you pay for borrowing money. MSME Pathways uses a flat interest rate, meaning you pay the same interest amount each month. Lower rates mean lower total cost.',
            'key_points': [
                'Flat rate: Same interest amount every month (not compounding)',
                'Default rate: 1.5% per month (18% per year), varies by product',
                'Compare rates before choosing a loan product'
            ]
        },
        'loan_process': {
            'title': 'The Loan Process',
            'content': 'Applying for a loan is simple with our AI-assisted process. When blockchain is enabled, major loan events are recorded on the blockchain for transparency. AI features require ai_consent (POST /api/auth/consent/).',
            'key_points': [
                'Step 1: Complete your profile (personal and business information)',
                'Step 2: Upload required documents (valid ID is always required)',
                'Step 3: Browse loan products and get AI pre-qualification (risk: low/medium/high; requires ai_consent)',
                'Step 4: Submit your application with your preferred amount and term',
                'Step 5: A loan officer reviews your application',
                'Step 6: Get approved or receive feedback on what to improve',
                'Step 7: Loan is disbursed via your preferred method',
                'Step 8: Repay in monthly installments'
            ]
        },
        'documents_needed': {
            'title': 'Documents You Need',
            'content': 'We keep requirements simple for MSMEs. Many small businesses operate informally, so we don\'t always require a business permit.',
            'key_points': [
                'Valid government ID (required for all loans)',
                'Selfie with your ID',
                'Proof of address (utility bill, barangay certificate)',
                'Business permit (DTI/SEC/Mayor\'s permit — if available)',
                'Business photo (photo of your business or workplace)',
                'Income proof (bank statements, sales records — optional)'
            ]
        },
        'improving_chances': {
            'title': 'Improving Your Approval Chances',
            'content': 'Tips to increase your likelihood of getting approved.',
            'key_points': [
                'Complete your profile fully',
                'Upload clear, valid documents',
                'Start with a smaller loan amount',
                'Show consistent business activity'
            ]
        },
        'payment_methods': {
            'title': 'Payment Methods',
            'content': 'MSME Pathways supports 5 payment methods in two categories: automatic and manual.',
            'key_points': [
                'AUTOMATIC — recorded instantly when you pay:',
                '  • GCash — pay using your GCash mobile wallet',
                '  • Bank Transfer — pay via electronic bank transfer',
                '  • Wallet (ETH) — pay using your Ethereum cryptocurrency wallet',
                'MANUAL — your loan officer records the payment for you:',
                '  • Cash — pay at a partner location',
                '  • Check — pay by check; recorded after clearance',
                'For cash and check, visit a partner location and your loan officer will record it in the system'
            ]
        },
        'repayment_schedule': {
            'title': 'Understanding Your Repayment Schedule',
            'content': 'After your loan is disbursed, a repayment schedule is automatically created with equal monthly installments.',
            'key_points': [
                'Each installment has a due date, principal portion, and interest portion',
                'Installment statuses: Pending, Paid, Partial, or Overdue',
                'Partial payments are supported — pay what you can',
                'Penalties may be applied for late payments; contact support if you need help',
                'View your schedule in the app: Track → select your loan → Schedule tab',
                'View payment history: Track → select your loan → Payments tab'
            ]
        },
        'blockchain_basics': {
            'title': 'Blockchain Verification',
            'content': 'When blockchain is enabled, MSME Pathways records major loan events on the Ethereum blockchain, providing a transparent and tamper-proof record of your loan history.',
            'key_points': [
                'Every loan application, approval, disbursement, and payment is recorded on-chain',
                'Blockchain records cannot be altered or deleted — ensuring transparency',
                'You can view blockchain verification details in the app',
                'This protects both borrowers and lenders with an immutable audit trail'
            ]
        },
        'after_approval': {
            'title': 'After Your Loan is Approved',
            'content': 'Once approved, here\'s what happens next and what you need to know about managing your loan.',
            'key_points': [
                'You\'ll receive a notification with your approved loan amount',
                'Set your preferred disbursement method (GCash, bank transfer, cash, check, or wallet)',
                'The loan officer processes the disbursement',
                'A repayment schedule is automatically created after disbursement',
                'Make monthly payments on time to maintain good standing',
                'Track everything in the app under the "Track" section'
            ]
        },
        'wallet_setup': {
            'title': 'Using the ETH Wallet',
            'content': 'MSME Pathways supports Ethereum (ETH) wallet payments for both disbursement and repayment. This is a cryptocurrency-based payment option.',
            'key_points': [
                'Wallet (ETH) is one of the 5 accepted payment methods',
                'Payments via ETH wallet are automatically recorded in the system',
                'You can also choose to receive your loan disbursement via ETH wallet',
                'All wallet transactions are verified on the Ethereum blockchain'
            ]
        }
    }
    
    def get(self, request, topic=None):
        """Get education content on loan topics"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result
        
        if topic:
            cache_key = f'ai_education_{topic}'
            cached_data = cache.get(cache_key)
            if cached_data:
                return success_response(data={**cached_data, 'cached': True})
            
            if topic in self.TOPICS:
                topic_data = self.TOPICS[topic]
                cache.set(cache_key, topic_data, CACHE_TTL.get('education', 86400))
                return success_response(data={**topic_data, 'cached': False})
            else:
                return error_response(
                    message="Topic not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
        
        cache_key = 'ai_education_topics_list'
        cached_list = cache.get(cache_key)
        if cached_list:
            return success_response(
                data={'topics': cached_list, 'cached': True},
                message="Education topics retrieved"
            )
        
        topic_list = [{'id': k, 'title': v['title']} for k, v in self.TOPICS.items()]
        cache.set(cache_key, topic_list, CACHE_TTL.get('education', 86400))
        return success_response(
            data={'topics': topic_list, 'cached': False},
            message="Education topics retrieved"
        )


class FAQsView(AccessControlMixin, APIView):
    """
    Get frequently asked questions.
    
    GET /api/ai/faqs/
    
    Responses are cached for performance (FAQs rarely change).
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    FAQS = [
        {
            'category': 'Loan Applications',
            'question': 'How much can I borrow?',
            'answer': 'Loan amounts depend on the product. Check the loan product page for the exact minimum and maximum amount, since each product can have different limits.'
        },
        {
            'category': 'Loan Applications',
            'question': 'How long does approval take?',
            'answer': 'Review time depends on the completeness of your application and loan officer workload. The app will show you the current status while it is being reviewed.'
        },
        {
            'category': 'Loan Applications',
            'question': 'What if I get rejected?',
            'answer': 'You can read the rejection feedback, improve the items that were missing, and resubmit the application once it is reset to draft.'
        },
        {
            'category': 'Documents',
            'question': 'Do I need a business permit?',
            'answer': 'Not necessarily! We understand many MSMEs operate informally. A valid government ID is the main requirement.'
        },
        {
            'category': 'Loan Payments',
            'question': 'How do I make payments?',
            'answer': 'If you are paying yourself, use GCash, bank transfer, or Wallet (ETH). Cash and check payments are recorded by a loan officer at the office or partner location.'
        },
        {
            'category': 'Loan Payments',
            'question': 'What happens if I miss a payment?',
            'answer': 'Your installment will be marked as overdue. Contact us immediately — we offer flexible arrangements for genuine difficulties.'
        },
        {
            'category': 'Loan Applications',
            'question': 'How do I check my loan status?',
            'answer': 'Open the app and go to Track → Applications. You\'ll see the current status of all your loan applications (draft, submitted, under review, approved, rejected, disbursed, or cancelled).'
        },
        {
            'category': 'Account & Profile',
            'question': 'How do I enable the AI assistant?',
            'answer': 'After logging in, turn on AI access in your account consent settings. AI access is separate from general data consent, and signing up does not turn it on automatically.'
        },
        {
            'category': 'Account & Profile',
            'question': 'How do I change the app language?',
            'answer': 'You can choose English or Tagalog during signup, or change it later in your app settings. The AI assistant will use your saved language when you do not pick one in chat.'
        },
        {
            'category': 'Getting Started',
            'question': 'What is blockchain verification?',
            'answer': 'When blockchain is enabled, major loan events such as application, approval, disbursement, and payments are recorded on the Ethereum blockchain. This creates a transparent, tamper-proof audit trail.'
        },
        {
            'category': 'Loan Payments',
            'question': 'How does the repayment schedule work?',
            'answer': 'After your loan is disbursed, a repayment schedule is automatically created with equal monthly installments. Each installment includes a principal and interest portion. You can view it in the app under Track → select your loan → Schedule tab.'
        },
        {
            'category': 'Loan Applications',
            'question': 'What happens after my loan is disbursed?',
            'answer': 'Once disbursed, your repayment schedule is automatically created. You\'ll need to make monthly payments according to the schedule. You can track your payments and remaining balance in the app under the Track section.'
        },
        {
            'category': 'Loan Payments',
            'question': 'What is the ETH Wallet payment method?',
            'answer': 'Wallet (ETH) lets you make payments using an Ethereum cryptocurrency wallet. Those payments are recorded in the system, and you can also choose it as a disbursement method if it is available for your application.'
        }
    ]
    
    def get(self, request):
        """Get FAQs"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result
        
        cache_key = 'ai_faqs'
        cached_data = cache.get(cache_key)
        if cached_data:
            return success_response(
                data={'faqs': cached_data, 'total': len(cached_data), 'cached': True},
                message="FAQs retrieved"
            )
        
        cache.set(cache_key, self.FAQS, CACHE_TTL.get('faqs', 86400))
        
        return success_response(
            data={'faqs': self.FAQS, 'total': len(self.FAQS), 'cached': False},
            message="FAQs retrieved"
        )
