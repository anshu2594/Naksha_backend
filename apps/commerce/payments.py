import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    inline_serializer,
)

from .inventory import release_order_inventory, reserve_order_inventory
from .models import (
    Order,
    PaymentRefund,
    PaymentWebhookEvent,
    RazorpayPayment,
)
from .serializers import OrderSerializer
from .views import Conflict, get_guest


logger = logging.getLogger(__name__)
RAZORPAY_API = "https://api.razorpay.com/v1"
GUEST_ID_PARAMETER = OpenApiParameter(
    name="X-Guest-ID",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.HEADER,
    required=True,
)
IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.HEADER,
    required=True,
)


class PaymentGatewayError(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The payment provider request failed."
    default_code = "payment_provider_error"

    def __init__(self, detail=None, *, definitive=False, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        self.definitive = definitive
        super().__init__(detail or self.default_detail)


class RazorpayGateway:
    def _credentials(self):
        key_id = getattr(settings, "RAZORPAY_KEY_ID", "")
        key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
        if not key_id or not key_secret:
            raise PaymentGatewayError(
                "Razorpay test credentials are not configured.",
                definitive=True,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not key_id.startswith("rzp_test_"):
            raise PaymentGatewayError(
                "Only Razorpay test-mode keys are enabled.",
                definitive=True,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return key_id, key_secret

    def request(self, method, path, payload=None):
        key_id, key_secret = self._credentials()
        token = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
        headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{RAZORPAY_API}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            logger.warning("Razorpay returned HTTP %s for %s %s", exc.code, method, path)
            raise PaymentGatewayError(
                "The payment provider rejected the request.", definitive=True
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            logger.exception("Razorpay network request failed for %s %s", method, path)
            raise PaymentGatewayError(
                "The payment provider could not be reached; the operation may still be processing."
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.exception("Razorpay returned an unreadable response for %s %s", method, path)
            raise PaymentGatewayError(
                "The payment provider returned an unreadable response."
            ) from exc

    def create_order(self, order, amount_paise):
        return self.request(
            "POST",
            "/orders",
            {
                "amount": amount_paise,
                "currency": "INR",
                "receipt": order.order_number,
                "notes": {"store_order": order.order_number},
            },
        )

    def get_payment(self, payment_id):
        return self.request("GET", f"/payments/{payment_id}")

    def refund(self, payment_id, amount_paise, receipt):
        return self.request(
            "POST",
            f"/payments/{payment_id}/refund",
            {"amount": amount_paise, "receipt": receipt[:40]},
        )


def _amount_in_paise(amount):
    return int((amount * Decimal("100")).quantize(Decimal("1")))


def _payment_signature(order_id, payment_id):
    secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
    if not secret:
        raise PaymentGatewayError(
            "Razorpay test credentials are not configured.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return hmac.new(
        secret.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _checkout_response(attempt):
    return {
        "keyId": settings.RAZORPAY_KEY_ID,
        "razorpayOrderId": attempt.gateway_order_id,
        "amount": _amount_in_paise(attempt.amount),
        "currency": attempt.currency,
        "orderId": attempt.order.order_number,
    }


class RazorpayCheckoutView(APIView):
    permission_classes = []
    authentication_classes = []

    @extend_schema(
        request=None,
        parameters=[GUEST_ID_PARAMETER, IDEMPOTENCY_PARAMETER],
        responses=inline_serializer(
            name="RazorpayCheckout",
            fields={
                "keyId": serializers.CharField(),
                "razorpayOrderId": serializers.CharField(),
                "amount": serializers.IntegerField(),
                "currency": serializers.CharField(),
                "orderId": serializers.CharField(),
            },
        ),
        operation_id="razorpay_checkout_create",
    )
    def post(self, request, order_number):
        guest = get_guest(request)
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key or len(idempotency_key) > 100:
            raise ValidationError(
                {"Idempotency-Key": "Supply a unique key of at most 100 characters."}
            )

        with transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update(),
                order_number=order_number,
                guest=guest,
            )
            if order.payment_method not in {
                Order.PaymentMethod.UPI,
                Order.PaymentMethod.CARD,
            }:
                raise ValidationError(
                    {"orderId": "Only UPI/card orders use Razorpay checkout."}
                )
            if order.status == Order.Status.CANCELLED:
                raise Conflict("Cancelled orders cannot start payment.")
            if order.payment_status != Order.PaymentStatus.PENDING:
                raise Conflict("This order is not awaiting payment.")
            if order.inventory_released and not reserve_order_inventory(order):
                raise Conflict("The order no longer has enough stock to retry payment.")

            existing_attempt = order.payments.filter(
                status=RazorpayPayment.Status.CREATED
            ).first()
            if existing_attempt and existing_attempt.idempotency_key != idempotency_key:
                raise Conflict(
                    "A payment attempt is already in progress for this order. Reuse its checkout."
                )

            request_hash = hashlib.sha256(
                f"{order.order_number}:{order.total}:INR".encode()
            ).hexdigest()
            attempt, created = RazorpayPayment.objects.get_or_create(
                idempotency_key=idempotency_key,
                defaults={
                    "order": order,
                    "request_hash": request_hash,
                    "amount": order.total,
                    "currency": "INR",
                },
            )
            if attempt.order_id != order.pk or attempt.request_hash != request_hash:
                raise Conflict("This idempotency key was already used for another payment.")
            if attempt.gateway_order_id:
                return Response(_checkout_response(attempt))
            if not created and attempt.status != RazorpayPayment.Status.CREATED:
                raise Conflict("This payment attempt cannot be retried with the same key.")
            if not created:
                return Response(
                    {"orderId": order.order_number, "status": "processing"},
                    status=status.HTTP_202_ACCEPTED,
                )

        try:
            result = RazorpayGateway().create_order(
                order,
                _amount_in_paise(attempt.amount),
            )
        except PaymentGatewayError as exc:
            if exc.definitive:
                _fail_payment_attempt(attempt.pk)
            raise
        if (
            not result.get("id")
            or result.get("amount") != _amount_in_paise(attempt.amount)
            or result.get("currency") != attempt.currency
        ):
            _fail_payment_attempt(attempt.pk)
            raise PaymentGatewayError(
                "Razorpay created an order with an unexpected amount or currency."
            )
        attempt.gateway_order_id = result["id"]
        attempt.save(update_fields=["gateway_order_id", "updated_at"])
        return Response(_checkout_response(attempt), status=status.HTTP_201_CREATED)


class RazorpayVerifyView(APIView):
    permission_classes = []
    authentication_classes = []

    @extend_schema(
        parameters=[GUEST_ID_PARAMETER],
        request=inline_serializer(
            name="RazorpayPaymentVerification",
            fields={
                "razorpay_order_id": serializers.CharField(),
                "razorpay_payment_id": serializers.CharField(),
                "razorpay_signature": serializers.CharField(),
            },
        ),
        responses=OrderSerializer,
        operation_id="razorpay_payment_verify",
    )
    def post(self, request, order_number):
        guest = get_guest(request)
        gateway_order_id = request.data.get("razorpay_order_id", "")
        payment_id = request.data.get("razorpay_payment_id", "")
        signature = request.data.get("razorpay_signature", "")
        if not all(isinstance(value, str) and value for value in (gateway_order_id, payment_id, signature)):
            raise ValidationError(
                {
                    "detail": "razorpay_order_id, razorpay_payment_id, and razorpay_signature are required."
                }
            )
        expected_signature = _payment_signature(gateway_order_id, payment_id)
        if not hmac.compare_digest(expected_signature, signature):
            raise ValidationError({"razorpay_signature": "Invalid payment signature."})

        attempt = get_object_or_404(
            RazorpayPayment.objects.select_related("order"),
            gateway_order_id=gateway_order_id,
            order__order_number=order_number,
            order__guest=guest,
        )
        if (
            attempt.status == RazorpayPayment.Status.CAPTURED
            and attempt.gateway_payment_id == payment_id
        ):
            return Response(OrderSerializer(attempt.order).data)
        payment = RazorpayGateway().get_payment(payment_id)
        if (
            payment.get("order_id") != gateway_order_id
            or payment.get("amount") != _amount_in_paise(attempt.amount)
            or payment.get("currency") != attempt.currency
            or payment.get("status") != "captured"
        ):
            raise ValidationError(
                {"payment": "Razorpay payment is not captured for this order amount/currency."}
            )

        with transaction.atomic():
            attempt = RazorpayPayment.objects.select_for_update().select_related(
                "order"
            ).get(pk=attempt.pk)
            if attempt.gateway_payment_id not in {None, payment_id}:
                raise Conflict("This checkout attempt is already linked to another payment.")
            attempt.gateway_payment_id = payment_id
            attempt.status = RazorpayPayment.Status.CAPTURED
            attempt.save(update_fields=["gateway_payment_id", "status", "updated_at"])
            Order.objects.filter(pk=attempt.order_id).update(
                payment_status=Order.PaymentStatus.PAID
            )
            attempt.order.refresh_from_db()
        return Response(OrderSerializer(attempt.order).data)


def _validate_webhook_payment(attempt, entity):
    if (
        entity.get("amount") != _amount_in_paise(attempt.amount)
        or entity.get("currency") != attempt.currency
    ):
        raise ValidationError("Razorpay event amount or currency does not match the order.")


def _fail_payment_attempt(attempt_id):
    with transaction.atomic():
        attempt = RazorpayPayment.objects.select_for_update().get(pk=attempt_id)
        attempt.status = RazorpayPayment.Status.FAILED
        attempt.save(update_fields=["status", "updated_at"])
        order = Order.objects.select_for_update().get(pk=attempt.order_id)
        other_attempts = RazorpayPayment.objects.filter(
            order=order, status=RazorpayPayment.Status.CREATED
        ).exists()
        if (
            order.payment_status == Order.PaymentStatus.PENDING
            and not other_attempts
        ):
            release_order_inventory(order)


def _handle_payment_event(event_type, entity):
    gateway_order_id = entity.get("order_id")
    payment_id = entity.get("id")
    if not gateway_order_id or not payment_id:
        raise ValidationError("Razorpay payment event is missing its payment or order ID.")
    try:
        attempt = RazorpayPayment.objects.select_for_update().select_related(
            "order"
        ).get(gateway_order_id=gateway_order_id)
    except RazorpayPayment.DoesNotExist as exc:
        raise ValidationError("Razorpay order does not match a local payment attempt.") from exc
    _validate_webhook_payment(attempt, entity)

    if event_type == "payment.captured":
        if attempt.gateway_payment_id not in {None, payment_id}:
            raise ValidationError("Razorpay payment ID conflicts with the existing attempt.")
        attempt.gateway_payment_id = payment_id
        attempt.status = RazorpayPayment.Status.CAPTURED
        attempt.save(update_fields=["gateway_payment_id", "status", "updated_at"])
        Order.objects.filter(pk=attempt.order_id).update(
            payment_status=Order.PaymentStatus.PAID
        )
    elif event_type == "payment.failed":
        if attempt.status != RazorpayPayment.Status.CAPTURED:
            attempt.gateway_payment_id = payment_id
            attempt.status = RazorpayPayment.Status.FAILED
            attempt.save(update_fields=["gateway_payment_id", "status", "updated_at"])
            has_other_pending = RazorpayPayment.objects.filter(
                order_id=attempt.order_id,
                status=RazorpayPayment.Status.CREATED,
            ).exclude(pk=attempt.pk).exists()
            if (
                not has_other_pending
                and attempt.order.payment_status == Order.PaymentStatus.PENDING
            ):
                release_order_inventory(attempt.order)


def _handle_refund_event(event_type, entity):
    refund_id = entity.get("id")
    payment_id = entity.get("payment_id")
    if not refund_id or not payment_id:
        raise ValidationError("Razorpay refund event is missing its refund or payment ID.")
    try:
        refund = PaymentRefund.objects.select_for_update().get(
            gateway_refund_id=refund_id
        )
    except PaymentRefund.DoesNotExist:
        try:
            attempt = RazorpayPayment.objects.select_related("order").get(
                gateway_payment_id=payment_id,
                status=RazorpayPayment.Status.CAPTURED,
            )
        except RazorpayPayment.DoesNotExist as exc:
            raise ValidationError("Razorpay refund does not match a captured payment.") from exc
        matching_refunds = PaymentRefund.objects.select_for_update().filter(
            order=attempt.order,
            amount=Decimal(entity.get("amount", 0)) / Decimal("100"),
            status=PaymentRefund.Status.PENDING,
            gateway_refund_id__isnull=True,
        )
        receipt = entity.get("receipt")
        if receipt:
            matching_refunds = matching_refunds.filter(
                idempotency_key=receipt
            )
        candidates = list(matching_refunds[:2])
        if len(candidates) != 1:
            raise ValidationError("Razorpay refund does not match one pending refund.")
        refund = candidates[0]
        refund.gateway_refund_id = refund_id

    if not RazorpayPayment.objects.filter(
        order_id=refund.order_id,
        gateway_payment_id=payment_id,
        status=RazorpayPayment.Status.CAPTURED,
    ).exists():
        raise ValidationError("Razorpay refund payment does not match this order.")
    if Decimal(entity.get("amount", 0)) != _amount_in_paise(refund.amount):
        raise ValidationError("Razorpay refund amount does not match the request.")
    if refund.status == PaymentRefund.Status.PROCESSED:
        if event_type == "refund.processed":
            return
        raise ValidationError("A processed refund cannot move to failed.")
    if refund.status == PaymentRefund.Status.FAILED:
        if event_type == "refund.failed":
            return
        raise ValidationError("A failed refund cannot move to processed.")
    refund.status = (
        PaymentRefund.Status.PROCESSED
        if event_type == "refund.processed"
        else PaymentRefund.Status.FAILED
    )
    refund.save(update_fields=["gateway_refund_id", "status", "updated_at"])
    if refund.status == PaymentRefund.Status.PROCESSED:
        _refresh_order_refund_status(refund.order_id)


def _refresh_order_refund_status(order_id):
    order = Order.objects.select_for_update().get(pk=order_id)
    refunded = PaymentRefund.objects.filter(
        order=order, status=PaymentRefund.Status.PROCESSED
    ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
    if refunded >= order.total:
        order.payment_status = Order.PaymentStatus.REFUNDED
    elif refunded > 0:
        order.payment_status = Order.PaymentStatus.PARTIALLY_REFUNDED
    order.save(update_fields=["payment_status", "updated_at"])


@method_decorator(csrf_exempt, name="dispatch")
class RazorpayWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        parameters=[
            OpenApiParameter(
                name="X-Razorpay-Signature",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
            ),
            OpenApiParameter(
                name="X-Razorpay-Event-Id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
            ),
        ],
        responses=inline_serializer(
            name="RazorpayWebhookResult",
            fields={"status": serializers.CharField()},
        ),
        operation_id="razorpay_webhook_receive",
    )
    def post(self, request):
        secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")
        signature = request.headers.get("X-Razorpay-Signature", "")
        event_id = request.headers.get("X-Razorpay-Event-Id", "").strip()
        if not secret:
            return JsonResponse(
                {"detail": "Razorpay webhook secret is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            return JsonResponse({"detail": "Invalid webhook signature."}, status=400)
        if not event_id or len(event_id) > 100:
            return JsonResponse({"detail": "A valid Razorpay event ID is required."}, status=400)
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JsonResponse({"detail": "Webhook body must be valid JSON."}, status=400)

        event_type = payload.get("event")
        payload_hash = hashlib.sha256(request.body).hexdigest()
        try:
            with transaction.atomic():
                existing = PaymentWebhookEvent.objects.select_for_update().filter(
                    event_id=event_id
                ).first()
                if existing:
                    if existing.payload_hash != payload_hash:
                        return JsonResponse(
                            {"detail": "Event ID was already used for a different payload."},
                            status=409,
                        )
                    return JsonResponse({"status": "duplicate"})

                body = payload.get("payload", {})
                if event_type in {"payment.captured", "payment.failed"}:
                    entity = body.get("payment", {}).get("entity", {})
                    _handle_payment_event(event_type, entity)
                elif event_type in {"refund.processed", "refund.failed"}:
                    entity = body.get("refund", {}).get("entity", {})
                    _handle_refund_event(event_type, entity)

                PaymentWebhookEvent.objects.create(
                    event_id=event_id,
                    event_type=str(event_type or "unknown")[:80],
                    payload_hash=payload_hash,
                )
        except ValidationError as exc:
            return JsonResponse({"detail": exc.detail}, status=400)
        except IntegrityError:
            existing = PaymentWebhookEvent.objects.filter(event_id=event_id).first()
            if existing and existing.payload_hash == payload_hash:
                return JsonResponse({"status": "duplicate"})
            raise
        return JsonResponse({"status": "processed"})


def create_refund(*, order, amount, idempotency_key, user):
    if len(idempotency_key) > 40:
        raise ValidationError(
            {"Idempotency-Key": "Key must be at most 40 characters for Razorpay receipts."}
        )
    request_hash = hashlib.sha256(
        f"{order.order_number}:{amount}".encode()
    ).hexdigest()
    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            existing = PaymentRefund.objects.filter(
                idempotency_key=idempotency_key
            ).first()
            if existing:
                if (
                    existing.order_id != order.pk
                    or existing.request_hash != request_hash
                ):
                    raise Conflict(
                        "This refund idempotency key was used with another request."
                    )
                return existing, False

            if order.payment_status not in {
                Order.PaymentStatus.PAID,
                Order.PaymentStatus.PARTIALLY_REFUNDED,
            }:
                raise Conflict("Only captured orders can be refunded.")
            attempt = (
                RazorpayPayment.objects.filter(
                    order=order,
                    status=RazorpayPayment.Status.CAPTURED,
                    gateway_payment_id__isnull=False,
                )
                .order_by("-created_at")
                .first()
            )
            if attempt is None:
                raise Conflict("No captured Razorpay payment exists for this order.")
            committed = PaymentRefund.objects.filter(
                order=order,
                status__in=[
                    PaymentRefund.Status.PENDING,
                    PaymentRefund.Status.PROCESSED,
                ],
            ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
            if amount > order.total - committed:
                raise ValidationError(
                    {"amount": "Refund exceeds the remaining captured order amount."}
                )
            refund = PaymentRefund.objects.create(
                order=order,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                amount=amount,
                created_by=user,
            )
    except IntegrityError:
        existing = PaymentRefund.objects.filter(
            idempotency_key=idempotency_key
        ).first()
        if existing is None:
            raise
        if existing.order_id != order.pk or existing.request_hash != request_hash:
            raise Conflict("This refund idempotency key was used with another request.")
        return existing, False

    try:
        result = RazorpayGateway().refund(
            attempt.gateway_payment_id,
            _amount_in_paise(amount),
            idempotency_key,
        )
    except PaymentGatewayError as exc:
        if exc.definitive:
            PaymentRefund.objects.filter(pk=refund.pk).update(
                status=PaymentRefund.Status.FAILED
            )
        raise

    if not result.get("id") or result.get("status") not in {
        "created",
        "pending",
        "processed",
    }:
        logger.error("Razorpay returned an incomplete refund response")
        raise PaymentGatewayError(
            "Razorpay returned an incomplete refund response; awaiting webhook reconciliation."
        )
    refund.gateway_refund_id = result.get("id")
    refund.status = (
        PaymentRefund.Status.PROCESSED
        if result.get("status") == "processed"
        else PaymentRefund.Status.PENDING
    )
    refund.save(update_fields=["gateway_refund_id", "status", "updated_at"])
    if refund.status == PaymentRefund.Status.PROCESSED:
        _refresh_order_refund_status(order.pk)
    return refund, True
