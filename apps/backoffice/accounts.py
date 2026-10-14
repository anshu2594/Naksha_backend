import re

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import generics, serializers, status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema

from .models import CustomerProfile


User = get_user_model()
PHONE_PATTERN = re.compile(r"^[+0-9() .-]{7,30}$")


class CustomerOnly(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and not request.user.is_staff
        )


class StrictInputMixin:
    def to_internal_value(self, data):
        unknown_fields = set(data) - set(self.fields)
        if unknown_fields:
            raise serializers.ValidationError(
                {field: "Unknown field." for field in sorted(unknown_fields)}
            )
        return super().to_internal_value(data)


class CustomerUserSerializer(serializers.ModelSerializer):
    firstName = serializers.CharField(source="first_name", required=False, allow_blank=True)
    lastName = serializers.CharField(source="last_name", required=False, allow_blank=True)
    isStaff = serializers.BooleanField(source="is_staff", read_only=True)
    role = serializers.SerializerMethodField()
    phone = serializers.CharField(source="customer_profile.phone", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "firstName",
            "lastName",
            "phone",
            "role",
            "isStaff",
        ]
        read_only_fields = ["id", "username", "phone", "role", "isStaff"]

    def get_role(self, instance) -> str:
        return "staff" if instance.is_staff else "customer"


class CustomerRegistrationSerializer(StrictInputMixin, serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirmPassword = serializers.CharField(write_only=True, trim_whitespace=False)
    firstName = serializers.CharField(max_length=150, required=False, allow_blank=True)
    lastName = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)

    def validate_username(self, value):
        value = value.strip()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_phone(self, value):
        if value and not PHONE_PATTERN.fullmatch(value):
            raise serializers.ValidationError("Enter a valid phone number.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["confirmPassword"]:
            raise serializers.ValidationError(
                {"confirmPassword": "The passwords do not match."}
            )
        candidate = User(
            username=attrs["username"],
            email=attrs["email"],
            first_name=attrs.get("firstName", ""),
            last_name=attrs.get("lastName", ""),
        )
        try:
            password_validation.validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        validated_data.pop("confirmPassword")
        password = validated_data.pop("password")
        first_name = validated_data.pop("firstName", "")
        last_name = validated_data.pop("lastName", "")
        phone = validated_data.pop("phone", "")
        with transaction.atomic():
            user = User.objects.create_user(
                password=password,
                first_name=first_name,
                last_name=last_name,
                **validated_data,
            )
            CustomerProfile.objects.create(
                user=user,
                email_normalized=user.email.casefold(),
                phone=phone,
            )
        return user


class CustomerProfileUpdateSerializer(StrictInputMixin, serializers.ModelSerializer):
    firstName = serializers.CharField(source="first_name", required=False, allow_blank=True)
    lastName = serializers.CharField(source="last_name", required=False, allow_blank=True)
    phone = serializers.CharField(
        source="customer_profile.phone", required=False, allow_blank=True, max_length=30
    )

    class Meta:
        model = User
        fields = ["email", "firstName", "lastName", "phone"]

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_phone(self, value):
        if value and not PHONE_PATTERN.fullmatch(value):
            raise serializers.ValidationError("Enter a valid phone number.")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        profile_data = validated_data.pop("customer_profile", {})
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if validated_data:
            instance.save()
        profile, _ = CustomerProfile.objects.get_or_create(user=instance)
        for field, value in profile_data.items():
            setattr(profile, field, value)
        if "email" in validated_data:
            profile.email_normalized = validated_data["email"].casefold()
        if profile_data:
            profile.save()
        elif "email" in validated_data:
            profile.save(update_fields=["email_normalized", "updated_at"])
        instance.customer_profile = profile
        return instance


class RegisteredCustomerAdminSerializer(serializers.ModelSerializer):
    firstName = serializers.CharField(source="first_name", read_only=True)
    lastName = serializers.CharField(source="last_name", read_only=True)
    isActive = serializers.BooleanField(source="is_active", read_only=True)
    dateJoined = serializers.DateTimeField(source="date_joined", read_only=True)
    phone = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "firstName",
            "lastName",
            "phone",
            "isActive",
            "dateJoined",
        ]

    def get_phone(self, instance) -> str:
        try:
            return instance.customer_profile.phone
        except CustomerProfile.DoesNotExist:
            return ""


class RegisteredCustomerAdminUpdateSerializer(
    StrictInputMixin, serializers.ModelSerializer
):
    firstName = serializers.CharField(source="first_name", required=False, allow_blank=True)
    lastName = serializers.CharField(source="last_name", required=False, allow_blank=True)
    isActive = serializers.BooleanField(source="is_active", required=False)
    phone = serializers.CharField(
        source="customer_profile.phone", required=False, allow_blank=True, max_length=30
    )

    class Meta:
        model = User
        fields = ["firstName", "lastName", "isActive", "phone"]

    def validate_phone(self, value):
        if value and not PHONE_PATTERN.fullmatch(value):
            raise serializers.ValidationError("Enter a valid phone number.")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        profile_data = validated_data.pop("customer_profile", {})
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if validated_data:
            instance.save()
        profile, _ = CustomerProfile.objects.get_or_create(user=instance)
        for field, value in profile_data.items():
            setattr(profile, field, value)
        if profile_data:
            profile.save()
        instance.customer_profile = profile
        return instance


class CustomerRegistrationView(APIView):
    permission_classes = []
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_register"

    @extend_schema(
        request=CustomerRegistrationSerializer,
        responses={201: CustomerUserSerializer},
        operation_id="auth_register_customer",
    )
    def post(self, request):
        serializer = CustomerRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            CustomerUserSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )


class CustomerProfileView(generics.RetrieveUpdateAPIView):
    authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, CustomerOnly]
    serializer_class = CustomerProfileUpdateSerializer

    def get_object(self):
        profile, _ = CustomerProfile.objects.get_or_create(user=self.request.user)
        return profile.user

    @extend_schema(
        responses=CustomerUserSerializer,
        operation_id="auth_customer_profile_retrieve",
    )
    def retrieve(self, request, *args, **kwargs):
        user = self.get_object()
        return Response(CustomerUserSerializer(user).data)

    @extend_schema(
        request=CustomerProfileUpdateSerializer,
        responses=CustomerUserSerializer,
        operation_id="auth_customer_profile_update",
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        user = self.get_object()
        serializer = self.get_serializer(user, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(CustomerUserSerializer(user).data)

    @extend_schema(
        request=CustomerProfileUpdateSerializer,
        responses=CustomerUserSerializer,
        operation_id="auth_customer_profile_partial_update",
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)
