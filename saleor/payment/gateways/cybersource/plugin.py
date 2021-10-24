from typing import TYPE_CHECKING

from django.conf import settings

from saleor.plugins.base_plugin import BasePlugin, ConfigurationTypeField

from ..utils import get_supported_currencies
from . import (
    GatewayConfig,
    GatewayResponse,
    authorize,
    capture,
    confirm,
    get_client_token,
    process_payment,
    refund,
    void,
)

from ... import ChargeStatus, TransactionKind

from . import csapi


GATEWAY_NAME = "CyberSource"        # Plugin name (for backend)
DISPLAY_NAME = "Credit/Debit Card"  # Display name for frontend

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

    PLUGIN_ID = "mirumee.payments.cybersource"
    PLUGIN_NAME = GATEWAY_NAME
    DEFAULT_ACTIVE = True

    DEFAULT_CONFIGURATION = [
        {"name": "profile-id", "value": None},
        {"name": "access-key", "value": None},
        {"name": "secret-key", "value": None},
        {"name": "is-live", "value": False},
        {"name": "locale", "value": csapi.LOCALE},
        {"name": "Store customers card", "value": False},
        {"name": "Automatic payment capture", "value": False},
        {"name": "Supported currencies", "value": csapi.CURRENCY},
    ]

    CONFIG_STRUCTURE = {
        "profile-id": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Profile ID of Payment Configuration.",
            "label": "Profile ID",
        },
        "access-key": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Required for authentication.",
            "label": "Access Key",
        },
        "secret-key": {
            "type": ConfigurationTypeField.SECRET,
            "help_text": "Signs the transaction data.",
            "label": "Secret Key",
        },
        "is-live": {
            "type": ConfigurationTypeField.BOOLEAN,
            "help_text": "Run in live mode.",
            "label": "Live Mode",
        },
        "locale": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Client/User locale.",
            "label": "Locale",
        },
        "Store customers card": {
            "type": ConfigurationTypeField.BOOLEAN,
            "help_text": "Determines if Saleor should store cards.",
            "label": "Store customers card",
        },
        "Automatic payment capture": {
            "type": ConfigurationTypeField.BOOLEAN,
            "help_text": "Determines if Saleor should automaticaly capture payments.",
            "label": "Automatic payment capture",
        },
        "Supported currencies": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Determines currencies supported by gateway."
            " Please enter currency codes separated by a comma.",
            "label": "Supported currencies",
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configuration = {item["name"]: item["value"] for item in self.configuration}
        connection_params = {
            "is_live": configuration["is-live"],
            "profile_id": configuration["profile-id"],
            "access_key": configuration["access-key"],
            "secret_key": configuration["secret-key"],
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
        return authorize(payment_information, self._get_gateway_config())

    @require_active_plugin
    def capture_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        return capture(payment_information, self._get_gateway_config())

    @require_active_plugin
    def confirm_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        return confirm(payment_information, self._get_gateway_config())

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

    def _cancel_payment(self, payment_information):
        #TODO: Cancel payment.
        return None

    def _confirm_payment(self, payment_information):
        #TODO: Confirm payment.
        return None

    def _create_payment(self, payment_information):
        token = get_client_token()
        data = {
            'amount': payment_information.amount,
            'currency': payment_information.currency,
            'reference_number': payment_information.order_id \
                    #or payment_information.graphql_payment_id,
                    or payment_information.payment_id,
            'transaction_uuid': token.replace('-', '')
        }
        return GatewayResponse(
            is_success=True,
            action_required=True,
            action_required_data={
                'action': self._cs.endpoint,
                'inputs': self._cs.process(data),
                'txn_id': token,
            },
            kind=TransactionKind.ACTION_TO_CONFIRM,
            amount=payment_information.amount,
            currency=payment_information.currency,
            transaction_id=token,
            error=None,
        )

    @require_active_plugin
    def process_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
        #FIXME: Find a better way to get state instead of token.
        state = payment_information.token or csapi.State.DEFAULT
        if state in csapi.State.STATES:
            if state == csapi.State.CREATE:
                response = self._create_payment(payment_information)
            elif state == csapi.State.CONFIRM:
                response = self._confirm_payment(payment_information)
            elif state == csapi.State.CANCEL:
                response = self._cancel_payment(payment_information)
            else:
                response = None
            #FIXME: Handle response.
            if response is not None:
                return response
        return process_payment(payment_information, self._get_gateway_config())

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
            #FIXME: Have to find a better way to get state instead of token.
            {"field": "default_payment_token", "value": csapi.State.DEFAULT},
        ]
