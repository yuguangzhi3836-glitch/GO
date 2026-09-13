class ExternalSandboxExecutor:
    """Provider-specific transport boundary. No default network implementation."""
    configured=False
    def execute(self,*_args,**_kwargs):
        raise ValueError('EXTERNAL_CONNECTOR_EXECUTOR_NOT_CONFIGURED')

external_sandbox_executor=ExternalSandboxExecutor()
