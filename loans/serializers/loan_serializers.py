from rest_framework import serializers
from loans.models import APPLICATION_STATUSES


class LoanProductSerializer(serializers.Serializer):
    """Serializer for loan product data"""
    id = serializers.CharField(read_only=True)
    name = serializers.CharField(max_length=100)
    code = serializers.CharField(max_length=20)
    description = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    min_amount = serializers.FloatField(min_value=1000)
    max_amount = serializers.FloatField(min_value=1000)
    interest_rate = serializers.FloatField(min_value=0, max_value=1)
    min_term_months = serializers.IntegerField(min_value=1)
    max_term_months = serializers.IntegerField(min_value=1)
    required_documents = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=['valid_id']
    )
    min_business_months = serializers.IntegerField(min_value=0, required=False, default=6)
    min_monthly_income = serializers.FloatField(min_value=0, required=False, default=5000)
    business_types = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=[]
    )
    target_description = serializers.CharField(required=False, allow_blank=True)
    active = serializers.BooleanField(default=True)

    def validate(self, data):
        if data.get('min_amount', 0) > data.get('max_amount', 0):
            raise serializers.ValidationError("min_amount cannot exceed max_amount")
        if data.get('min_term_months', 0) > data.get('max_term_months', 0):
            raise serializers.ValidationError("min_term cannot exceed max_term")
        return data


class LoanApplicationSerializer(serializers.Serializer):
    """Serializer for loan application submission"""
    product_id = serializers.CharField(required=True)
    requested_amount = serializers.FloatField(min_value=1000)
    term_months = serializers.IntegerField(min_value=1)
    purpose = serializers.CharField(max_length=500, required=False, allow_blank=True)


class LoanApplicationResponseSerializer(serializers.Serializer):
    """Serializer for application response"""
    id = serializers.CharField()
    product_id = serializers.CharField()
    product_name = serializers.CharField(required=False)
    requested_amount = serializers.FloatField()
    recommended_amount = serializers.FloatField(allow_null=True)
    approved_amount = serializers.FloatField(allow_null=True)
    term_months = serializers.IntegerField()
    purpose = serializers.CharField()
    status = serializers.CharField()
    eligibility_score = serializers.FloatField(allow_null=True)
    risk_category = serializers.CharField(allow_null=True)
    submitted_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class LoanReviewSerializer(serializers.Serializer):
    """Serializer for loan officer review"""
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    approved_amount = serializers.FloatField(min_value=0, required=False)
    rejection_reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def validate(self, data):
        if data['action'] == 'approve' and not data.get('approved_amount'):
            raise serializers.ValidationError({
                'approved_amount': 'Required when approving'
            })
        if data['action'] == 'reject' and not data.get('rejection_reason'):
            raise serializers.ValidationError({
                'rejection_reason': 'Required when rejecting'
            })
        return data
