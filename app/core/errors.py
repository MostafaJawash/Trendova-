class AppError(Exception):
    def __init__(self, status_code, code, message, details=None, headers=None):
        self.status_code, self.code, self.message, self.details, self.headers = status_code, code, message, details, headers or {}
