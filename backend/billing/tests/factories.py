import datetime
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth.models import User

from accounts.models import Company, Freelancer
from billing.enums import BillingRunStatus
from billing.models import BillingRun, Invoice, InvoiceLine
from contracts.models import Contract, TimesheetEntry


def make_freelancer(name: str = 'Another Freelancer') -> Freelancer:
    username = f'freelancer-{uuid4().hex}@test.test'
    user = User.objects.create_user(username=username, email=username)
    return Freelancer.objects.create(user=user, name=name)


def make_contract(
    company: Company,
    freelancer: Freelancer,
    daily_rate: Decimal = Decimal('400.00'),
) -> Contract:
    return Contract.objects.create(
        company=company,
        freelancer=freelancer,
        daily_rate=daily_rate,
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 12, 31),
    )


def make_entry(
    contract: Contract,
    day: datetime.date,
    status: str = TimesheetEntry.STATUS_APPROVED,
    hours: Decimal = Decimal('8.00'),
) -> TimesheetEntry:
    return TimesheetEntry.objects.create(contract=contract, date=day, hours=hours, status=status)


def make_invoice(
    contract: Contract,
    triggered_by: User,
    period_start: datetime.date,
    period_end: datetime.date,
    line_days: list[datetime.date],
) -> Invoice:
    run = BillingRun.objects.create(
        company=contract.company,
        period_start=period_start,
        period_end=period_end,
        triggered_by=triggered_by,
        status=BillingRunStatus.COMPLETED,
    )
    invoice = Invoice.objects.create(
        billing_run=run,
        company=contract.company,
        freelancer=contract.freelancer,
        period_start=period_start,
        period_end=period_end,
    )
    for day in line_days:
        entry = make_entry(contract, day)
        InvoiceLine.objects.create(
            invoice=invoice,
            timesheet_entry=entry,
            date=day,
            hours=entry.hours,
            daily_rate=contract.daily_rate,
        )
    return invoice
