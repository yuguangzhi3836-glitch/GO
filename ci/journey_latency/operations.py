"""Normal operations only. No replay, retries, suppliers or HTTP transport."""
from types import SimpleNamespace


class Operations:
    def __init__(self):
        from go_hotel.api.routes.mobility import rb, RideBook, order
        from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
        self.book, self.body_type, self.query = rb, RideBook, order
        self.bridge = vertical_transaction_bridge

    def execute(self, operation, task):
        owner = task['owner']
        principal = SimpleNamespace(user_id=owner)
        if operation == 'create_order':
            result = self.book(self.body_type(**task['body']), principal, task['key'])['data']
            assert result['status'] == 'PAYMENT_PENDING', 'CREATE_STATE'
            assert result['total_amount_minor'] == 16800 and result['currency'] == 'CNY', 'CREATE_MONEY'
            return {'owner': owner, 'order_id': result['order_id'], 'state': result['status']}
        if operation == 'payment_confirm':
            result = self.bridge.checkout_contract('RIDE', task['order_id'], owner,
                'ride-engineering-source', 'isolated://journey/' + task['order_id'], 'isolated-method')
            assert result['state'] == 'PAYMENT_CONFIRMED_AWAITING_SUPPLIER', 'PAYMENT_STATE'
            assert result['supplier_fulfillment_id'] and result['capture_id'], 'PAYMENT_FACT_MISSING'
            return {'owner': owner, 'order_id': task['order_id'], **result}
        if operation == 'order_query':
            result = self.query(task['order_id'], principal)['data']
            assert result['order_id'] == task['order_id'] and result['status'] == 'COMPLETED', 'QUERY_STATE'
            assert result['total_amount_minor'] == 16800 and result['currency'] == 'CNY', 'QUERY_MONEY'
            return {'owner': owner, 'order_id': result['order_id'], 'state': result['status']}
        raise ValueError('UNKNOWN_JOURNEY_OPERATION')
