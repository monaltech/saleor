# CyberSource Payment Gateway -- Utilities

from typing import Optional

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError

from ....checkout.models import Checkout
from ....checkout.complete_checkout import complete_checkout
from ....discount.utils import fetch_active_discounts
from ....payment.models import Payment, Transaction

from . import GATEWAY_ID
from ... import ChargeStatus


CHARGE_STATUS = {
    ChargeStatus.FULLY_CHARGED,
    ChargeStatus.NOT_CHARGED,
    ChargeStatus.PARTIALLY_CHARGED,
    ChargeStatus.PENDING,
}

NO_CREATE_ORDER = 'Order not created for ChargeStatus=%s'
NO_CHECKOUT_OBJ = 'No Checkout object in Payment object.'

PREFIXES = ['api.', 'mgapi.']

ADDRESS_MAP = {
    'first_name': 'bill_to_forename',
    'last_name': 'bill_to_surname',
    #'company_name': '',
    'street_address_1': 'bill_to_address_line1',
    'street_address_2': 'bill_to_address_line2',
    'city': 'bill_to_address_city',
    #'city_area': '',
    'postal_code': 'bill_to_address_postal_code',
    'country': 'bill_to_address_country',
    #'country_area': '',
    'phone': 'bill_to_phone',
}


import logging

_logger = logging.getLogger(__name__)


def map_address(address, email=None):
    addr = {i: getattr(address, i, None) for i in ADDRESS_MAP}
    data = {ADDRESS_MAP[k]: v for k, v in addr.items() if v is not None}
    state = getattr(address, 'country_area', None) \
            or getattr(address, 'city_area', None)
    if state is not None:
        data['bill_to_address_state'] = state
    if email is not None:
        data['bill_to_email'] = email
    return data


def build_redirect_url(request, url, add_port=False):
    redirect = request.GET.get('redirect')
    if not redirect:
        host = request.get_host()
        for prefix in PREFIXES:
            if host.startswith(prefix):
                redirect = host[len(prefix):]
                break
        if add_port and ':' not in host:
            port = request.get_port()
            if port and int(port) not in [80, 443]:
                redirect += f':{port}'
    if redirect:
        if '://' not in redirect:
            redirect = f'{request.scheme}://{redirect}'
        #url = f'{redirect}{url}'
        return f'{redirect}{url}'
    return request.build_absolute_uri(url)


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
