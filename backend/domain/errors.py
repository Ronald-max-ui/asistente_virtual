"""Safe application errors; HTTP translation belongs to the API boundary."""
class DomainError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)

class SessionError(DomainError):
    pass

class ProviderTimeout(DomainError):
    def __init__(self): super().__init__('provider_timeout', 503)

class ProviderUnavailable(DomainError):
    def __init__(self): super().__init__('provider_unavailable', 502)

class CommercialInputError(DomainError):
    def __init__(self): super().__init__('invalid_commercial_input', 422)
