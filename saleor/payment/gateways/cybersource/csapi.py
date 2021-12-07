# CyberSource Payment Gateway API

import hmac
import hashlib
import uuid

from datetime import datetime, timezone

from base64 import b64encode
from decimal import Decimal


import logging

_logger = logging.getLogger(__name__)


# Payment Gateway API endpoint URLs:
LIVE_URL = 'https://secureacceptance.cybersource.com/pay'
TEST_URL = 'https://testsecureacceptance.cybersource.com/pay'

AMOUNT_FORMAT = '%.2f'  # Format (decimal-precision) of amount.

CURRENCY = 'NPR'    # Currency used for order/payment transaction.
LOCALE = 'en'       # Language to use for customer-facing content.

PAYMENT_METHOD = 'card' # Default payment method.

AUTH = 'authorization'  # Authorization/Hold the Payment.
CAPTURE = 'sale'        # Capture (Transfer) the Payment.

CREATE_TOKEN = 'create_payment_token'   # Create customer's payment card token.
UPDATE_TOKEN = 'update_payment_token'   # Update customer's payment card token.

TRANSACTION_TYPES = [
    f'{AUTH}',                      # Authorization/Hold the payment.
    f'{AUTH},{CREATE_TOKEN}',       # Not Used (implemented) for now.
    f'{AUTH},{UPDATE_TOKEN}',       # Not Used (implemented) for now.
    f'{CAPTURE}',                   # Capture (Transfer) the payment.
    f'{CAPTURE},{CREATE_TOKEN}',    # Not Used (implemented) for now.
    f'{CAPTURE},{UPDATE_TOKEN}',    # Not Used (implemented) for now.
]

DEFAULT_TOKEN = 'create'    # Initial payment token.

SIGNED_FIELD_SEP = ','  # Data (to-be-signed) field seperator.
SIGNED_VALUE_SEP = '='  # Data (to-be-signed) value seperator.

# Format of the timestamp field.
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

REQUIRED_FIELDS = {
    'access_key',
    'amount',
    'currency',
    'locale',
    'profile_id',
    'reference_number',
    #'signature',
    'signed_date_time',
    'signed_field_names',
    'transaction_type',
    'transaction_uuid',
    'unsigned_field_names',
}

SIGNED_FIELDS = {
    *REQUIRED_FIELDS,
    'bill_to_forename',
    'bill_to_surname',
    'bill_to_phone',
    'bill_to_email',
    'bill_to_address_line1',
    'bill_to_address_line2',
    'bill_to_address_city',
    'bill_to_address_postal_code',
    'bill_to_address_state',
    'bill_to_address_country',
    'merchant_id',
    'payment_method',
}

ADDED_FIELDS = {
    'access_key',
    'currency',
    'locale',
    'merchant_id',
    'payment_method',
    'profile_id',
    #'signature',
    'signed_date_time',
    'signed_field_names',
    'transaction_type',
    'transaction_uuid',
    'unsigned_field_names',
}

CHECK_FIELDS = REQUIRED_FIELDS - ADDED_FIELDS

EXTRA_FIELDS = [
    'signed_field_names',
    'unsigned_field_names',
    #'signature',
]


E_AMOUNT = 'Amount format or type is invalid.'
E_CONFIG = 'Missing configuration parameters.'

E_SIGNATURE = 'Signature does not match.'

E_NO_SIGN_FIELD = 'No signature field in payment data.'
E_NO_SIGN_VALUE = 'No signature value in payment data.'

E_CHECK_FIELDS = 'Required fields check failed.'
E_MISSING_FIELD = 'Field "%s" is missing in payment data.'
E_REQ_FIELDS = 'Required field(s) are missing.'

E_NOKEY = 'Missing field(s) in payment data.'
E_VALUE = 'Invalid value(s) in payment data.'


class Status:

    ACCEPT = 'ACCEPT'
    REVIEW = 'REVIEW'
    DECLINE = 'DECLINE'
    CANCEL = 'CANCEL'
    ERROR = 'ERROR'

    LABELS = {
        ACCEPT: 'Accepted',
        REVIEW: 'In Review',
        DECLINE: 'Declined',
        CANCEL: 'Cancelled',
        ERROR: 'Error!',
    }

    MESSAGES = {
        ACCEPT: 'Payment accepted',
        REVIEW: 'Payment is in review',
        DECLINE: 'Payment was declined',
        CANCEL: 'Payment is cancelled',
        ERROR: 'Payment processing error',
    }

    RETURN = {
        ACCEPT,
        REVIEW,
    }

    CONFIRM = RETURN
    SUCCESS = RETURN

    FAILED = {
        CANCEL,
        DECLINE,
        ERROR,
    }

    @classmethod
    def label(cls, name, default=None):
        if default is None:
            default = name
        return cls.LABELS.get(name, default)

    @classmethod
    def message(cls, name, default=''):
        return cls.MESSAGES.get(name, default)


class Response:

    def __init__(self, data):
        self._code = data.get('reason_code', 0)
        self._text = data.get('decision', None)
        if self._code is None:
            self._code = 0
        self._data = data

    def __getattr__(self, name):
        try:
            return self._data[name]
        except KeyError:
            pass
        c = self.__class__.__name__
        e = f"'{c}' object has no attribute '{name}'"
        raise AttributeError(e)

    def __str__(self):
        return f'{self._text} ({self._code}) {self.message}'

    def add(self, name, value):
        if name not in self._data:
            self._data[name] = value
            return True
        return False

    @property
    def code(self):
        return self._code

    @property
    def data(self):
        return self._data.copy()

    def get(self, name, default=None):
        return self._data.get(name, default)

    @property
    def message(self):
        msg = self._data.get('message', '')
        if not msg:
            return Status.message(self._text)
        return msg

    @property
    def status(self):
        return self._text

    def update(self, data):
        result = {k: self.add(k, v) \
                for k, v in data.items()}
        return result


class CyberSourceError(Exception):

    def __init__(*args, code=0):
        super().__init__(*args)
        self.code = code

    @property
    def message(self):
        return str(self)


class SignatureError(CyberSourceError):

    def __init__(self, code=99):
        super().__init__(*args, code=code)


class ValidationError(CyberSourceError):

    def __init__(*args, code=50, source=None):
        super().__init__(*args, code=code)
        self.source = source


class CyberSource:

    def __init__(self, config):
        try:
            self.merchant_id = config['merchant_id']
            self.profile_id = config['profile_id']
            self.access_key = config['access_key']
            self.secret_key = config['secret_key']
            self.is_live = config.get('is_live', False)
            self.auto_capture = config.get('auto_capture', True)
            self.locale = config.get('locale', LOCALE)
        except KeyError as e:
            _logger.exception(f'CyberSource: {E_CONFIG}')
            raise ValidationError(E_CONFIG, source=e)

    def _add_missing(self, result):
        if 'currency' not in result:
            result['currency'] = CURRENCY
        if 'locale' not in result:
            result['locale'] = LOCALE
        if 'payment_method' not in result and \
                'payment_method' in ADDED_FIELDS:
            result['payment_method'] = PAYMENT_METHOD
        if 'signed_date_time' not in result:
            timestamp = datetime.now(timezone.utc).strftime(TS_FORMAT)
            result['signed_date_time'] = timestamp
        if 'transaction_uuid' not in result:
            #result['transaction_uuid'] = uuid.uuid4().hex
            result['transaction_uuid'] = str(uuid.uuid4())
        return result

    def _create_result(self, data):
        result = data.copy()
        result['profile_id'] = self.profile_id
        result['access_key'] = self.access_key
        result['transaction_type'] = CAPTURE \
                if self.auto_capture else AUTH
        if 'merchant_id' in ADDED_FIELDS:
            result['merchant_id'] = self.merchant_id
        if AMOUNT_FORMAT is not None:
            self._format_amount(result)
        self._add_missing(result)
        return result

    def _format_amount(self, result):
        try:
            amount = result['amount']
            types = (Decimal, float, int)
            if isinstance(amount, str) or not \
                    isinstance(amount, types):
                # amount = float(amount)
                amount = Decimal(amount)
            amount = AMOUNT_FORMAT % amount
            result['amount'] = amount
        except (TypeError, ValueError) as e:
            _logger.exception(f'FormatAmount: {E_AMOUNT}')
            raise ValidationError(E_AMOUNT, source=e)
        except KeyError as e:
            msg = E_MISSING_FIELD % 'amount'
            _logger.exception(f'FormatAmount: {msg}')
            raise ValidationError(msg, source=e)

    @property
    def endpoint(self):
        if self.is_live:
            return LIVE_URL
        return TEST_URL

    @staticmethod
    def html(data, glue='\n', sort=False):
        if sort:
            return glue.join(
                '<input type="hidden" name="%s" value="%s" />' \
                    % (i, data[i]) for i in sorted(data.keys())
            )
        return glue.join(
            f'<input type="hidden" name="{k}" value="{v}" />' \
                for k, v in data.items()
        )

    def process(self, data, html=False, glue='\n'):
        if CHECK_FIELDS.issubset(data.keys()):
            result = self._create_result(data)
            fields = result.keys()
            signed = set([f for f in fields if f in SIGNED_FIELDS])
            signed.update(EXTRA_FIELDS)
            unsigned = set([f for f in fields if f not in signed])
            signed, unsigned = sorted(signed), sorted(unsigned)
            result['signed_field_names'] = ','.join(signed)
            result['unsigned_field_names'] = ','.join(unsigned)
            if REQUIRED_FIELDS.issubset(fields):
                result['signature'] = self.sign(result, signed)
                if html:
                    return self.html(result, glue)
                return result
            _logger.warning(f'CyberSource.process: {E_CHECK_FIELDS}')
            raise ValidationError(E_CHECK_FIELDS)
        _logger.warning('CyberSource.process: {E_REQ_FIELDS}')
        raise ValidationError(E_REQ_FIELDS)

    def sign(self, data, fields=None,
            field_sep=SIGNED_FIELD_SEP,
            value_sep=SIGNED_VALUE_SEP):
        data_to_sign = self.tosign(data, fields=fields,
                field_sep=field_sep, value_sep=value_sep)
        digest = hmac.new(self.secret_key.encode(),
                msg=data_to_sign.encode(),
                digestmod=hashlib.sha256).digest()
        return b64encode(digest).decode()

    @staticmethod
    def tosign(data, fields=None,
            field_sep=SIGNED_FIELD_SEP,
            value_sep=SIGNED_VALUE_SEP):
        try:
            if fields is None:
                fields = data['signed_field_names'].split(field_sep)
            if value_sep is not None:
                vals = [f'{f}{value_sep}%s' % data[f] for f in fields]
            else:
                vals = [str(data[f]) for f in fields]
            return field_sep.join(vals)
        except (TypeError, ValueError) as e:
            _logger.exception(f'CyberSource.tosign: {E_VALUE}')
            raise ValidationError(E_VALUE, source=e)
        except KeyError as e:
            _logger.exception(f'CyberSource.tosign: {E_NOKEY}')
            raise ValidationError(E_NOKEY, source=e)

    def validate(self, data):
        try:
            signature = data['signature']
        except KeyError:
            raise ValidationError(E_NO_SIGN_FIELD)
        if not signature:
            raise ValidationError(E_NO_SIGN_VALUE)
        #TODO: Validate all other required fields.
        if signature != self.sign(data):
            raise SignatureError(E_SIGNATURE)
        return Response(data)


# Generate test html form.
if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        amount = float(sys.argv[1])
    else:
        amount = 100.0
    refnum = datetime.now().strftime("%Y%m%d%H%M%S")
    config = {
        'merchant_id': '100710070000046',
        'profile_id': 'F1A9A61D-44FE-489D-A167-925D0A669D26',
        'access_key': '028c5892be8233baba7baa30837c46e7',
        'secret_key': '99aae74b5abf45a494406cd9411aa93f231f1947d8be474ebdbc389fe6a0327017c2560ee6064e92b72922b63670941d88d81072416242f4931d52daf66da518131041cc6be04160b95cd9dde6bcfb99ce9cb11446054876aa8c2ab687067299ae456f34e3a84539bc0a884ac00a80c80ca762ac48f847a087550daa13da9ed7',
        'auto_capture': True,
        'is_live': False,
    }
    data = {
        'amount': amount,
        'bill_to_forename': "Bibek",
        'bill_to_surname': "Shrestha",
        'bill_to_email': "bibek@example.com",
        'bill_to_phone': "977-9841234567",
        'bill_to_address_line1': "Lainchaur",
        'bill_to_address_city': "Kathmandu",
        'bill_to_address_postal_code': "44600",
        'bill_to_address_state': "Bagmati",
        'bill_to_address_country': "NP",
        'reference_number': refnum,
    }
    cs = CyberSource(config)
    result = cs.process(data)
    rows = ['''
                <tr>
                  <td style="text-align: right;">{field}</td>
                  <td style="text-align: left;">{value}</td>
                </tr>
            '''.format(field=f, value=result[f]) \
                    for f in sorted(result.keys())]
    glue = '\n' + ' ' * 20
    html = '''
        <html>
          <head>
            <title>CyberSource Test</title>
          </head>
          <body>
            <h1>CyberSource Payment Gateway Test</h1>
            <p>
              <strong>Endpoint URL</strong>: {endpoint}
            </p>
            <form action="{endpoint}" method="POST">
              <table border="1" cellpadding="4" cellspacing="0">
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                </tr>
                {rows}
                <tr>
                  <td colspan="2" style="text-align: center;">
                    {html}
                    <input type="submit" value=" Pay Now " />
                  </td>
                </tr>
              </table>
            </form>
            <p style="overflow-wrap: anywhere;">
              <strong>Signed Data</strong>: "{tosign}"
            </p>
          </body>
        </html>
    '''.format(
            endpoint=cs.endpoint,
            rows=''.join(rows),
            html=cs.html(result, glue, True),
            tosign=cs.tosign(result))
    print(html)

