from typing import TYPE_CHECKING

from django.conf import settings

from saleor.plugins.base_plugin import BasePlugin, ConfigurationTypeField

from ..utils import get_supported_currencies
from . import (
    GatewayConfig,
    authorize,
    capture,
    confirm,
    get_client_token,
    process_payment,
    refund,
    void,
)


from . import csapi


_PLUGIN_NAME = "CyberSource"        # Plugin name (for backend)
GATEWAY_NAME = "Credit/Debit Card"  # Display name for frontend


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
    PLUGIN_NAME = _PLUGIN_NAME
    DEFAULT_ACTIVE = True

    DEFAULT_CONFIGURATION = [
        {"name": "profile-id", "value": None},
        {"name": "access-key", "value": None},
        {"name": "secret-key", "value": None},
        {"name": "is-live", "value": False},
        {"name": "locale", "value": csapi.LOCALE},
        {"name": "Store customers card", "value": False},
        {"name": "Automatic payment capture", "value": True},
        {"name": "Supported currencies", "value": csapi.CURRENCY},
    ]

    CONFIG_STRUCTURE = {
        "profile-id": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Profile ID of Payment Gateway configuration.",
            "label": "Profile ID",
        },
        "access-key": {
            "type": ConfigurationTypeField.SECRET,
            "help_text": "Required for authentication with the Payment Gateway.",
            "label": "Access Key",
        },
        "secret-key": {
            "type": ConfigurationTypeField.SECRET,
            "help_text": "Signs transaction data with this key to prevent tempering.",
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
        self.config = GatewayConfig(
            gateway_name=GATEWAY_NAME,
            connection_params={
                "is_live": configuration["is-live"],
                "profile_id": configuration["profile-id"],
                "access_key": configuration["access-key"],
                "secret_key": configuration["secret-key"],
                "locale": configuration["locale"],
            },
            auto_capture=configuration["Automatic payment capture"],
            supported_currencies=configuration["Supported currencies"],
            store_customer=configuration["Store customers card"],
        )

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
    def process_payment(
        self, payment_information: "PaymentData", previous_value
    ) -> "GatewayResponse":
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
        return [{"field": "store_customer_card", "value": config.store_customer}]
