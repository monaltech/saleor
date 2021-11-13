# CyberSource Payment Gateway -- Utilities

from typing import Optional

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError

from .plugins import GATEWAY_ID

from ....checkout.models import Checkout
from ....checkout.complete_checkout import complete_checkout
from ....discount.utils import fetch_active_discounts
from ....payment.models import Payment, Transaction

from ... import ChargeStatus


CHARGE_STATUS = {
    ChargeStatus.FULLY_CHARGED,
    ChargeStatus.NOT_CHARGED,
    ChargeStatus.PARTIALLY_CHARGED,
    ChargeStatus.PENDING,
}

NO_CREATE_ORDER = 'Order not created for ChargeStatus=%s'
NO_CHECKOUT_OBJ = 'No Checkout object in Payment object.'


import logging

_logger = logging.getLogger(__name__)


def create_order(payment: Payment, checkout: Checkout, pd=None):
    if payment.charge_status in CHARGE_STATUS:
        try:
            discounts = fetch_active_discounts()
            user = checkout.user or AnonymousUser()
            order, ar, ad = complete_checkout(
                    checkout=checkout,
                    payment_data=pd or {},
                    store_source=False,
                    discounts=discounts,
                    user=user)
            return order
        except ValidationError:
            _logger.exception('create_order')
            payment_refund_or_void(payment)
        finally:
            payment.refresh_from_db()
    else:
        msg = f'create_order: {NO_CREATE_ORDER}'
        _logger.info(msg, payment.charge_status)
    return None


def get_checkout(payment: Payment) -> Optional[Checkout]:
    if payment.checkout:
        return (
            Checkout.objects.select_for_update(of=("self",))
            .prefetch_related("gift_cards", "lines__variant__product",)
            .select_related("shipping_method__shipping_zone")
            .filter(pk=payment.checkout.pk)
            .first()
        )
    _logger.warning(f'get_checkout: {NO_CHECKOUT_OBJ}')
    return None


def get_payment(payment_id, check_if_active=False) -> Optional[Payment]:
    payments = (
        Payment.objects.prefetch_related("checkout", "order")
        .select_for_update(of=("self",))
        .filter(id=payment_id, gateway=GATEWAY_ID)
    )
    if check_if_active:
        payments = payments.filter(is_active=True)
    return payments.first()


def make_searchable(token):
    #FIXME: Remove '-' for now.
    return token.replace('-', '')
