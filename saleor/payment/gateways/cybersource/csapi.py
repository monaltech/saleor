# CyberSource Payment Gateway API

import hmac
import hashlib
import uuid

from datetime import datetime, timezone

from base64 import b64encode
from decimal import Decimal

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
    'bill_to_address_line1',
    'bill_to_address_line2',
    'bill_to_address_city',
    'bill_to_address_postal_code',
    'bill_to_address_state',
    'bill_to_address_country',
    'payment_method',
}

ADDED_FIELDS = {
    'access_key',
    'currency',
    'locale',
    #'payment_method',
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


class State:
    CANCEL = 'cancel'
    CONFIRM = 'confirm'
    CREATE = 'create'
    STATES = {
        CANCEL,
        CONFIRM,
        CREATE,
    }
    DEFAULT = CREATE


class CyberSource:

    def __init__(self, config, auto_capture=True):
        try:
            self.profile_id = config['profile_id']
            self.access_key = config['access_key']
            self.secret_key = config['secret_key']
            self.is_live = config.get('is_live', False)
            self.locale = config.get('locale', LOCALE)
            self.auto_capture = auto_capture
        except KeyError as e:
            #FIXME: Raise custom exception.
            raise e

    def _add_missing(self, result):
        if 'currency' not in result:
            result['currency'] = CURRENCY
        if 'locale' not in result:
            result['locale'] = LOCALE
        #if 'payment_method' not in result:
        #    result['payment_method'] = PAYMENT_METHOD
        if 'signed_date_time' not in result:
            timestamp = datetime.now(timezone.utc).strftime(TS_FORMAT)
            result['signed_date_time'] = timestamp
        if 'transaction_uuid' not in result:
            result['transaction_uuid'] = uuid.uuid4().hex
        return result

    def _create_result(self, data):
        result = data.copy()
        result['profile_id'] = self.profile_id
        result['access_key'] = self.access_key
        result['transaction_type'] = CAPTURE \
                if self.auto_capture else AUTH
        try:
            if AMOUNT_FORMAT is not None:
                self._format_amount(result)
            self._add_missing(result)
        except KeyError as e:
            #FIXME: Raise custom exception.
            raise e
        return result

    def _format_amount(self, result):
        amount = result['amount']
        try:
            types = (Decimal, float, int)
            if isinstance(amount, str) or not \
                    isinstance(amount, types):
                # amount = float(amount)
                amount = Decimal(amount)
            amount = AMOUNT_FORMAT % amount
        except (TypeError, ValueError) as e:
            #FIXME: Raise custom exception.
            raise e
        result['amount'] = amount

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
            #FIXME: Raise custom exception.
            raise Exception('Required fields check failed.')
        else:
            #FIXME: Raise custom exception.
            raise Exception('Required fields are missing.')

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
        except TypeError as e:
            #FIXME: Raise custom exception.
            raise e
        except ValueError as e:
            #FIXME: Raise custom exception.
            raise e
        except KeyError as e:
            #FIXME: Raise custom exception.
            raise e


# Generate test html form.
if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        amount = float(sys.argv[1])
    else:
        amount = 100.0
    refnum = datetime.now().strftime("%Y%m%d%H%M%S")
    config = {
        'profile_id': 'F1A9A61D-44FE-489D-A167-925D0A669D26',
        'access_key': '028c5892be8233baba7baa30837c46e7',
        'secret_key': '99aae74b5abf45a494406cd9411aa93f231f1947d8be474ebdbc389fe6a0327017c2560ee6064e92b72922b63670941d88d81072416242f4931d52daf66da518131041cc6be04160b95cd9dde6bcfb99ce9cb11446054876aa8c2ab687067299ae456f34e3a84539bc0a884ac00a80c80ca762ac48f847a087550daa13da9ed7',
    }
    data = {
        'amount': amount,
        #'bill_to_forename': "Bibek",
        #'bill_to_surname': "Shrestha",
        #'bill_to_phone': "9841234567",
        #'bill_to_address_line1': "Lainchaur",
        #'bill_to_address_city': "Kathmandu",
        #'bill_to_address_postal_code': "44600",
        #'bill_to_address_state': "Bagmati",
        #'bill_to_address_country': "NP",
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
