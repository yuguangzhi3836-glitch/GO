from __future__ import annotations
from go_hotel.repositories.sql import repo
from go_hotel.services.booking import booking_service
from go_hotel.flight.service import flight_service
from go_hotel.services.mutation_boundary import MutationBoundary
from go_hotel.services.flight_command_lease import flight_command_lease

class SagaRecoveryWorker:
    def recover_expired_flight_commands(self, limit: int) -> tuple[int, int]:
        """Complete expired local Flight commands without asking the consumer to retry.

        payment_recovery performs the authoritative root/attempt/movement check;
        unknown or externally-invoked attempts stay fenced as reconciliation
        required and are never resent by this worker.
        """
        recovered = failed = 0
        # Claim each command just before executing it. A batch of leases would
        # otherwise expire in the queue behind a slow preceding command.
        for _ in range(limit):
            claims = repo.claim_expired_flight_recovery(1)
            if not claims:
                break
            claim = claims[0]
            operation, payload, token = claim['operation'], claim['payload'], claim['token']
            boundary = MutationBoundary(recovering=True)
            try:
                with flight_command_lease(operation, claim['key'], claim['resource_id'], token):
                    if operation == 'FLIGHT_CHECKOUT':
                        result = {'data': flight_service.recover_checkout(
                            payload['user_id'], payload['order_id'], payload['payment_method_id'], boundary)}
                    elif operation == 'FLIGHT_EXECUTE_CHANGE':
                        result = {'data': flight_service.recover_execute_change(
                            payload['user_id'], payload['order_id'], payload['quote_id'], payload.get('confirmation'), boundary)}
                    else:
                        raise ValueError('FLIGHT_RECOVERY_OPERATION_UNSUPPORTED')
                repo.finish_recoverable_idempotency(operation, claim['key'], payload, claim['resource_id'], token,
                                                    'COMPLETE', result)
                recovered += 1
            except Exception:
                try:
                    repo.finish_recoverable_idempotency(operation, claim['key'], payload, claim['resource_id'], token,
                                                        'RECOVERY_REQUIRED')
                except Exception:
                    pass
                failed += 1
        return recovered, failed

    async def run_once(self, limit: int = 100) -> dict:
        flight_recovered, flight_failed = self.recover_expired_flight_commands(limit)
        ops = repo.recoverable_operations(limit)
        recovered = flight_recovered
        failed = flight_failed
        for op in ops:
            try:
                if op["operation_type"] == "SUPPLIER_BOOK":
                    await booking_service.recover_confirmation(op)
                elif op["operation_type"] == "PAYMENT_CAPTURE_AFTER_BOOK":
                    await booking_service.recover_capture(op)
                elif op["operation_type"] == "PAYMENT_AUTHORIZE":
                    await booking_service.recover_authorization(op)
                else:
                    continue
                recovered += 1
            except Exception as exc:
                repo.mark_reconcile_required(op["operation_id"], str(exc)); failed += 1
        return {"scanned": len(ops) + flight_recovered + flight_failed, "recovered": recovered, "failed": failed}

recovery_worker = SagaRecoveryWorker()
