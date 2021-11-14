import uuid

from ... import ChargeStatus, TransactionKind
from ...interface import GatewayConfig, GatewayResponse, PaymentData, PaymentMethodInfo


GATEWAY_ID = 'mirumee.payments.cybersource'


def cybersource_success():
    return True


def get_client_token(**_):
    return str(uuid.uuid4())


def is_client_token(token, strict=False):
    if token:
        try:
            if not isinstance(token, str):
                token = str(token)
            if strict:
                canonical = uuid.UUID(token, version=4)
                return str(canonical) == token
            uuid.UUID(token)
            return True
        except (TypeError, ValueError):
            return False
    return None


def authorize(
    payment_information: PaymentData, config: GatewayConfig
) -> GatewayResponse:
    success = cybersource_success()
    error = None
    if not success:
        error = "Unable to authorize transaction"
    return GatewayResponse(
        is_success=success,
        action_required=False,
        kind=TransactionKind.AUTH,
        amount=payment_information.amount,
        currency=payment_information.currency,
        transaction_id=payment_information.token,
        error=error,
        payment_method_info=PaymentMethodInfo(
            last_4="1234",
            exp_year=2222,
            exp_month=12,
            brand="cybersource_visa",
            name="Holder name",
            type="card",
        ),
    )


def void(payment_information: PaymentData, config: GatewayConfig) -> GatewayResponse:
    error = None
    success = cybersource_success()
    if not success:
        error = "Unable to void the transaction."
    return GatewayResponse(
        is_success=success,
        action_required=False,
        kind=TransactionKind.VOID,
        amount=payment_information.amount,
        currency=payment_information.currency,
        transaction_id=payment_information.token,
        error=error,
    )


def capture(payment_information: PaymentData, config: GatewayConfig) -> GatewayResponse:
    """Perform capture transaction."""
    error = None
    success = cybersource_success()
    if not success:
        error = "Unable to process capture"

    return GatewayResponse(
        is_success=success,
        action_required=False,
        kind=TransactionKind.CAPTURE,
        amount=payment_information.amount,
        currency=payment_information.currency,
        transaction_id=payment_information.token,
        error=error,
        payment_method_info=PaymentMethodInfo(
            last_4="1234",
            exp_year=2222,
            exp_month=12,
            brand="cybersource_visa",
            name="Holder name",
            type="card",
        ),
    )


def confirm(payment_information: PaymentData, config: GatewayConfig) -> GatewayResponse:
    """Perform confirm transaction."""
    error = None
    success = cybersource_success()
    if not success:
        error = "Unable to process capture"

    return GatewayResponse(
        is_success=success,
        action_required=False,
        kind=TransactionKind.CAPTURE,
        amount=payment_information.amount,
        currency=payment_information.currency,
        transaction_id=payment_information.token,
        error=error,
    )


def refund(payment_information: PaymentData, config: GatewayConfig) -> GatewayResponse:
    error = None
    success = cybersource_success()
    if not success:
        error = "Unable to process refund"
    return GatewayResponse(
        is_success=success,
        action_required=False,
        kind=TransactionKind.REFUND,
        amount=payment_information.amount,
        currency=payment_information.currency,
        transaction_id=payment_information.token,
        error=error,
    )


def process_payment(
    payment_information: PaymentData, config: GatewayConfig
) -> GatewayResponse:
    """Process the payment."""
    response = authorize(payment_information, config)
    if config.auto_capture:
        response = capture(payment_information, config)
    return response


def _process_payment(
    payment_information: PaymentData, config: GatewayConfig
) -> GatewayResponse:
    """Process the payment."""
    token = payment_information.token

    # Process payment normally if payment token is valid
    if token not in dict(ChargeStatus.CHOICES):
        return capture(payment_information, config)

    # Process payment by charge status which is selected in the payment form
    # Note that is for testing by cybersource gateway only
    charge_status = token
    authorize_response = authorize(payment_information, config)
    if charge_status == ChargeStatus.NOT_CHARGED:
        return authorize_response

    if not config.auto_capture:
        return authorize_response

    capture_response = capture(payment_information, config)
    if charge_status == ChargeStatus.FULLY_REFUNDED:
        return refund(payment_information, config)
    return capture_response
