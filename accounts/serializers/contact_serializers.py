from rest_framework import serializers


class ContactSupportSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=100)
    contact_email = serializers.EmailField()
    concern_type = serializers.CharField(max_length=100)
    message = serializers.CharField(max_length=2000)
