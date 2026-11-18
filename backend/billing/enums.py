from enum import StrEnum


class BillingRunStatus(StrEnum):
    PENDING = 'pending'
    COMPLETED = 'completed'
    FAILED = 'failed'


class InvoiceEmailRecipient(StrEnum):
    COMPANY = 'company'
    FREELANCER = 'freelancer'


class InvoiceEmailStatus(StrEnum):
    PENDING = 'pending'
    SENT = 'sent'
    FAILED = 'failed'
