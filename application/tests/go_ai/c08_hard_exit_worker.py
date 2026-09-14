"""Test-only hard-exit worker: no remote providers, no configured business DB."""
import os
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import Base, GoAIInvocationRow, GoAIRequestRow
from go_hotel.go_ai import service as service_module
from go_hotel.go_ai.registry import GOAIProviderRegistry
from test_c08_synthesis_audit_finalization import SynthesisProvider


def main(database, calls_path, checkpoint):
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    Base.metadata.create_all(engine, tables=[GoAIRequestRow.__table__, GoAIInvocationRow.__table__])
    service_module.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    class CountingProvider(SynthesisProvider):
        def generate(self, request):
            with Path(calls_path).open("a") as file:
                file.write(request.task_type + "\n")
                file.flush()
                os.fsync(file.fileno())
            return super().generate(request)
    service = service_module.GOAIService(GOAIProviderRegistry([CountingProvider()]))
    record = service._record_attempt
    def interrupt_attempt(*args, **kwargs):
        if checkpoint == "before_invocation_commit":
            os._exit(73)
        record(*args, **kwargs)
        if checkpoint == "after_invocation_commit":
            os._exit(73)
    service._record_attempt = interrupt_attempt
    complete = service._complete_request
    def interrupt_complete(*args, **kwargs):
        complete(*args, **kwargs)
        if checkpoint == "after_completion_commit":
            os._exit(73)
    service._complete_request = interrupt_complete
    service.orchestrate(message="Hello", account_id="c08_crash_owner")
    raise AssertionError("Hard-exit checkpoint was not reached")


if __name__ == "__main__":
    main(*sys.argv[1:])
