# CyberSource Payment Gateway Webhooks

from ....core.transactions import transaction_with_commit_on_errors

from ....payment.models import (
    Payment,
    Transaction,
)

from ...interface import GatewayResponse
from ... import PaymentError, TransactionKind

from ...utils import (
    create_transaction,
    gateway_postprocess,
)

from .csapi import (
    #CyberSource,
    CyberSourceError,
    #Response,
    SignatureError,
    Status,
    ValidationError,
)

from . import GATEWAY_ID, is_client_token


PAYMENT_ID = 'req_reference_number'
TOKEN_NAME = 'req_transaction_uuid'


L_NOT_FOUND = "Payment not found for reference_number=%s."
E_NOT_FOUND = "Payment information not found for Ref# %s."

L_CHECKOUT = 'Checkout not found for: %s.'
E_CHECKOUT = 'Unable to process checkout.'

L_ORDER = 'Order not found for: %s.'
E_ORDER = 'Unable to process order.'

E_BAD_RESP = 'Unable to validate response sent by Payment Gateway.'
E_BAD_SIGN = 'Cannot verify response data sent by Payment Gateway.'

E_PROCESSING = 'Error processing response from Payment Gateway.'
E_VALIDATION = 'Error validating response from Payment Gateway.'


import logging

_logger = logging.getLogger(__name__)


class HandlerError(Exception): pass


class Handler:

    def __init__(self, payment, response):
        self.payment = payment
        self.response = response
        self.token = response[TOKEN_NAME]

    def _gateway_response(self, kind, action_required):
        response = self.response
        transaction_id = self.token
        searchable_key = make_searchable(transaction_id)
        raw_response = {str(k): str(v) \
                for k, v in response.items()}
        gateway_response = GatewayResponse(
                is_success=True, kind=kind,
                action_required=action_required,
                amount=response['req_amount'],
                currency=response['req_currency'],
                transaction_id=transaction_id,
                searchable_key=searchable_key,
                raw_response=raw_response,
                error="")
        return gateway_response

    def _get_transaction(self, kind=None, action_required=True):
        if kind is None:
            kind = TransactionKind.ACTION_TO_CONFIRM
        transaction = self.payment.transactions.filter(
                is_success=True, action_required=action_required,
                token=self.token, kind=kind).last()
        return transaction

    def _new_transaction(self, kind=None, action_required=True, post_process=False):
        if kind is None:
            kind = TransactionKind.ACTION_TO_CONFIRM
        gateway_response = self._gateway_response(kind)
        transaction = create_transaction(
                self.payment, action_required=action_required,
                kind=kind, payment_information=None,
                gateway_response=gateway_response)
        if transaction and post_process:
            gateway_postprocess(transaction, self.payment)
        return transaction

    def _update_transaction(self, transaction, kind=None, action_required=None):
        to_update = []
        if kind is not None and \
                transaction.kind != kind:
            transaction.kind = kind
            to_update.append('kind')
        if action_required is not None and \
                transaction.action_required != action_required:
            transaction.action_required = action_required
            to_update.append('action_required')
        if not transaction.searchable_key:
            searchable_key = make_searchable(self.token)
            transaction.searchable_key = searchable_key
            to_update.append('searchable_key')
        if not transaction.raw_response:
            transaction.raw_response = self.response
            to_update.append('raw_response')
        if to_update:
            transaction.save(update_fields=to_update)
        return len(to_update)

    def _process_transaction(self, kind, action_required):
        transaction = self._get_transaction(kind, action_required)
        if not transaction:
            transaction = self._new_transaction(kind,
                    action_required, post_process=True)
        else:
            self._update_transaction(transaction,
                    kind=None, action_required=None)
        return transaction

    def _create_order(self, transaction,
            payment=None, response=None):
        if payment is None:
            payment = self.payment
        if payment.order:
            return payment.order
        if response is None:
            response = self.response
        if payment.checkout:
            order = create_order(payment,
                payment.checkout, pd=response
            )
            if not order:
                _logger.warning(L_ORDER % self.token)
                raise HandlerError(E_ORDER)
            return order
        _logger.warning(E_CHECKOUT % self.token)
        raise HandlerError(E_CHECKOUT)

    def process(capture=False):
        transaction = self._process_transaction(
                kind=TransactionKind.ACTION_TO_CONFIRM,
                action_required=True)
        payment, response = self.payment, self.response
        transaction = gateway.confirm(payment, response)
        if payment.token != transaction.token \
                and not is_client_token(payment.token) \
                and is_client_token(transaction.token):
            payment.token = transaction.token
            payment.save(update_fields=['token'])
        self._create_order(transaction, payment, response)
        return transaction


@transaction_with_commit_on_errors()
def handle_webhook(cs, data, *args, **kwargs):
    try:
        response = cs.validate(data)
        _logger.info('handle_webhook: %s', str(response))
    except ValidationError as e:
        _logger.warning('handle_webhook: %s', E_BAD_RESP)
        raise PaymentError(E_BAD_RESP, code=e.code)
    except SignatureError as e:
        _logger.warning('handle_webhook: %s', E_BAD_SIGN)
        raise PaymentError(E_BAD_SIGN, code=e.code)
    if response.status in Status.RETURN:
        payment = get_payment(response[PAYMENT_ID])
        if not payment:
            _logger.warning(L_NOT_FOUND, payment_id)
            e = E_NOT_FOUND % payment_id
            raise PaymentError(e)
        if payment.to_confirm:
            try:
                handler = Handler(payment, response)
                handler.process(cs.auto_capture)
            except ValidationError as e:
                _logger.exception(f'handle_webhook: {E_VALIDATION}')
                raise PaymentError(E_VALIDATION, code=e.code)
            except CyberSourceError as e:
                _logger.exception(f'handle_webhook: {E_PROCESSING}')
                raise PaymentError(E_PROCESSING, code=e.code)
            except HandlerError as e:
                _logger.exception('handle_webhook: %s', e)
                raise PaymentError(str(e))
    return response

