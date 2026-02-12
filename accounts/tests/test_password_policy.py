from django.test import SimpleTestCase

from accounts.serializers.auth_serializers import SignUpSerializer
from accounts.serializers.password_serializers import (
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
)


class PasswordPolicySerializerTests(SimpleTestCase):
    def test_signup_rejects_weak_password(self):
        serializer = SignUpSerializer(
            data={
                "first_name": "Test",
                "last_name": "User",
                "email": "signup-weak@example.com",
                "password": "123456",
                "password_confirm": "123456",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("password", serializer.errors)

    def test_signup_accepts_strong_password(self):
        serializer = SignUpSerializer(
            data={
                "first_name": "Test",
                "last_name": "User",
                "email": "signup-strong@example.com",
                "password": "S3curePass!123",
                "password_confirm": "S3curePass!123",
            }
        )

        self.assertTrue(serializer.is_valid())

    def test_reset_password_rejects_weak_password(self):
        serializer = ResetPasswordSerializer(
            data={
                "email": "reset-weak@example.com",
                "otp": "123456",
                "new_password": "123456",
                "confirm_password": "123456",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("new_password", serializer.errors)

    def test_reset_password_accepts_strong_password(self):
        serializer = ResetPasswordSerializer(
            data={
                "email": "reset-strong@example.com",
                "otp": "123456",
                "new_password": "S3curePass!123",
                "confirm_password": "S3curePass!123",
            }
        )

        self.assertTrue(serializer.is_valid())

    def test_change_password_rejects_weak_password(self):
        serializer = ChangePasswordSerializer(
            data={
                "old_password": "OldPass!123",
                "new_password": "123456",
                "confirm_password": "123456",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("new_password", serializer.errors)

    def test_change_password_accepts_strong_password(self):
        serializer = ChangePasswordSerializer(
            data={
                "old_password": "OldPass!123",
                "new_password": "N3wPass!456",
                "confirm_password": "N3wPass!456",
            }
        )

        self.assertTrue(serializer.is_valid())

    def test_forgot_password_flow_does_not_accept_password_input(self):
        serializer = ForgotPasswordSerializer(
            data={
                "email": "forgot@example.com",
                "password": "123456",
            }
        )

        self.assertTrue(serializer.is_valid())
        self.assertNotIn("password", serializer.validated_data)
