from typing import TYPE_CHECKING

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.utils.http import urlencode

from saleor.plugins.base_plugin import BasePlugin, ConfigurationTypeField

from ..utils import get_supported_currencies
from ... import TransactionKind, PaymentError

from . import (
    GATEWAY_ID,
    csapi,
    GatewayConfig,
    GatewayResponse,
    #authorize,
    #capture,
    #confirm,
    get_client_token,
    is_client_token,
    #process_payment,
    refund,
    void,
)

from .utils import (
    #create_order,
    #get_checkout,
    get_payment,
    make_searchable,
)

from .webhooks import handle_webhook

from base64 import b64encode
import json


GATEWAY_NAME = "CyberSource"        # Plugin name (for backend)
DISPLAY_NAME = "Credit/Debit Card"  # Display name for frontend

WEBHOOK_RETURN = '/return'          # Return URL
WEBHOOK_CANCEL = '/cancel'          # Cancel URL

WEBHOOK_NOTIFY = '/notify'          # Payment notification.

PAYMENT_QS = 'payment=%s'   # Payment response query string.

STATUS_FIELD = 'decision'   # Payment response status field.


E_PAYMENT_NOT_FOUND = 'Payment not found for payment_id=%s.'


if TYPE_CHECKING:
    from ...interface import GatewayResponse, PaymentData, TokenConfig


def require_active_plugin(fn):

    def wrapped(self, *args, **kwargs):
        previous = kwargs.get("previous_value", None)
        if not self.active:
            return previous
        return fn(self, *args, **kwargs)

    return wrapped


class CyberSourceGatewayPlugin(BasePlugin):

    PLUGIN_ID = GATEWAY_ID
    PLUGIN_NAME = GATEWAY_NAME
    DEFAULT_ACTIVE = True

    DEFAULT_CONFIGURATION = [
        {"name": "merchant-id", "value": None},
        {"name": "profile-id", "value": None},
        {"name": "access-key", "value": None},
        {"name": "secret-key", "value": None},
        {"name": "is-live", "value": False},
        {"name": "return-url", "value": None},
        {"name": "cancel-url", "value": None},
        {"name": "auto-capture", "value": True},
        {"name": "Automatic payment capture", "value": False},
        {"name": "Store customers card", "value": False},
        {"name": "Supported currencies", "value": csapi.CURRENCY},
        {"name": "locale", "value": csapi.LOCALE},
    ]

    CONFIG_STRUCTURE = {
        "merchant-id": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Merchant ID at the Payment Gateway.",
            "label": "Merchant ID",
        },
        "profile-id": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Profile ID of Payment Configuration.",
            "label": "Profile ID",
        },
        "access-key": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Required for authentication with Gateway.",
            "label": "Access Key",
        },
        "secret-key": {
            "type": ConfigurationTypeField.SECRET,
            "help_text": "Required for signing the transaction data.",
            "label": "Secret Key",
        },
        "is-live": {
            "type": ConfigurationTypeField.BOOLEAN,
            "help_text": "Run in live mode.",
            "label": "Live Mode",
        },
        "return-url": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Return to this URL after payment.",
            "label": "Return URL",
        },
        "cancel-url": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Return to this URL if payment canceled.",
            "label": "Cancel URL",
        },
        "auto-capture": {
            "type": ConfigurationTypeField.BOOLEAN,
            "help_text": "Automatically capture (transfer) the funds when a payment is made.",
            "label": "Automatic payment capture",
        },
        "Automatic payment capture": {
            "type": ConfigurationTypeField.BOOLEAN,
            "help_text": "Payments are marked as captured, keep disabled for manual review.",
            "label": "Mark payments as captured",
        },
        "Store customers card": {
            "type": ConfigurationTypeField.BOOLEAN,
            "help_text": "Store credit/debit card information in our database.",
            "label": "Store customers card",
        },
        "Supported currencies": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Determines currencies supported by the Gateway.",
            "label": "Supported currencies",
        },
        "locale": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Language for Payment Gateway user interface.",
            "label": "Locale",
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configuration = {item["name"]: item["value"] for item in self.configuration}
        connection_params = {
            "merchant_id": configuration["merchant-id"],
            "profile_id": configuration["profile-id"],
            "access_key": configuration["access-key"],
            "secret_key": configuration["secret-key"],
            "is_live": configuration["is-live"],
            "return_url": configuration["return-url"],
            "cancel_url": configuration["cancel-url"],
            "autp_capture": configuration["auto-capture"],
            "locale": configuration["locale"],
        }
        self.config = GatewayConfig(
            gateway_name=DISPLAY_NAME,
            connection_params=connection_params,
            auto_capture=configuration["Automatic payment capture"],
            supported_currencies=configuration["Supported currencies"],
            store_customer=configuration["Store customers card"],
        )
        self._cs = csapi.CyberSource(connection_params)

    def _get_gateway_config(self):
        return self.config

    @require_active_plugin
    def authorize_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        #return authorize(payment_information, self._get_gateway_config())
        return self._process_payment(
            payment_information, TransactionKind.AUTH
        )

    @require_active_plugin
    def capture_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        #return capture(payment_information, self._get_gateway_config())
        return self._process_payment(
            payment_information, TransactionKind.CAPTURE
        )

    @require_active_plugin
    def confirm_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        #return confirm(payment_information, self._get_gateway_config())
        return self._process_payment(
            payment_information, TransactionKind.CONFIRM
        )

    @require_active_plugin
    def refund_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        return refund(payment_information, self._get_gateway_config())

    @require_active_plugin
    def void_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        return void(payment_information, self._get_gateway_config())

    @require_active_plugin
    def token_is_required_as_payment_input(self, previous_value):
        #return True
        return False

    def _create_ard(self, payment_information, token):
        data = {
            'amount': payment_information.amount,
            'currency': payment_information.currency,
            #'reference_number': payment_information.order_id \
            #        #or payment_information.graphql_payment_id,
            #        or payment_information.payment_id,
            'reference_number': payment_information.payment_id,
            #'reference_number': payment_information.graphql_payment_id,
            #'transaction_uuid': token.replace('-', ''),
            'transaction_uuid': token,
        }
        return {
            'action': self._cs.endpoint,
            'inputs': self._cs.process(data),
            'txn_id': token,
        }

    def _create_response(self, payment_information, kind, data=None):
        if data is not None:
            token = data.get('transaction_id',
                    payment_information.token)
            token = data.pop('token', token)
        else:
            token = payment_information.token
            data = {}
        response = {
            'kind': kind,
            'is_success': True,
            'action_required': False,
            'action_required_data': {},
            'amount': payment_information.amount,
            'currency': payment_information.currency,
            'transaction_id': token,
            'searchable_key': make_searchable(token),
            'errors': None,
            **data}
        return GatewayResponse(**response)

    def _create_payment(self, payment_information, token=None):
        if token is None:
            token = get_client_token()
        ard = self._create_ard(payment_information, token)
        data = {
            'action_required': True,
            'action_required_data': ard,
            'transaction_id': token,
            #'transaction_already_processed': True,
        }
        return self._create_response(payment_information,
            TransactionKind.ACTION_TO_CONFIRM, data=data,
        )

    def _get_payment(self, payment_information):
        payment_id = payment_information.payment_id
        payment = get_payment(payment_id)
        if not payment:
            raise PaymentError(E_PAYMENT_NOT_FOUND % payment_id)
        return payment

    def _confirm_payment(self, kind, payment_information, payment=None):
        if payment is None:
            payment = self._get_payment(payment_information)
        #FIXME: Confirm/Validate using payment transactions.
        if payment_information.data:
            status = payment_information.data.get(STATUS_FIELD, None)
            if status is not None and status in csapi.Status.CONFIRM:
                if kind in {
                    TransactionKind.CAPTURE,
                    TransactionKind.CONFIRM,
                }:
                    if status == csapi.Status.CAPTURE:
                        return TransactionKind.CAPTURE
                    #if status == csapi.Status.REVIEW:
                    #    return TransactionKind.AUTH
                    return TransactionKind.AUTH
                return kind
            #FIXME: Check other status, ex: CANCEL, DECLINE, etc.
        return TransactionKind.ACTION_TO_CONFIRM

    def _process_payment(self, payment_information, kind=None):
        if not is_client_token(payment_information.token):
            return self._create_payment(
                    payment_information, get_client_token())
        if kind is None or kind == TransactionKind.CONFIRM:
            kind = self._get_default_kind()
        payment = self._get_payment(payment_information)
        if payment.to_confirm:
            kind = self._confirm_payment(kind,
                    payment_information, payment)
        data = {
            'action_required': kind == \
                    TransactionKind.ACTION_TO_CONFIRM,
            #'transaction_already_processed': True,
        }
        if payment_information.data:
            data['raw_response'] = {str(k): str(v) \
                    for k, v in payment_information.data.items()}
        return self._create_response(
            payment_information, kind, data=data
        )

    def _get_default_kind(self):
        if not self.auto_capture:
            return TransactionKind.AUTH
        return TransactionKind.CAPTURE

    @require_active_plugin
    def process_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        #return process_payment(payment_information, self._get_gateway_config())
        return self._process_payment(payment_information)

    def _webhook_redirect(self, response, status=None, config=None):
        if status is None:
            status = response.status
        if config is None:
            config = self._get_gateway_config()
        params = config.connection_params
        if status in csapi.Status.RETURN:
            url = params['return_url'] or '/'
        else:
            url = params['cancel_url'] or '/'
        if url.startswith('/'):
            url = request.build_absolute_uri(url)
        qs = PAYMENT_QS % urlencode(b64encode(json.dumps({
            'code': response.code,
            'label': csapi.Status.label(status),
            'message': response.message,
            'status': status,
        })))
        return HttpResponseRedirect(f'{url}?%s' % qs)

    def webhook(self, request: WSGIRequest, path: str, previous_value) -> HttpResponse:
        notify = path.startswith(WEBHOOK_NOTIFY)
        if notify or path.startswith(WEBHOOK_RETURN):
            try:
                data = request.POST.copy()
                #config = self._get_gateway_config()
                #response = handle_webhook(self, data, config)
                response = handle_webhook(self, data)
                if notify:
                    return HttpResponse('OK')
                status = response.status
            except PaymentError as e:
                if notify:
                    return HttpResponse('ERROR')
                status = csapi.Status.ERROR
                response = csapi.Response({
                    'decision': status,
                    'reason_code': e.code,
                    'message': e.message,
                })
            return self._webhook_redirect(response, status)
        return HttpResponseNotFound()

    @require_active_plugin
    def get_client_token(self, token_config: "TokenConfig", previous_value):
        return get_client_token()

    @require_active_plugin
    def get_supported_currencies(self, previous_value):
        config = self._get_gateway_config()
        return get_supported_currencies(config, GATEWAY_NAME)

    @require_active_plugin
    def get_payment_config(self, previous_value):
        config = self._get_gateway_config()
        return [
            {"field": "store_customer_card", "value": config.store_customer},
            {"field": "default_payment_token", "value": csapi.DEFAULT_TOKEN},
        ]
