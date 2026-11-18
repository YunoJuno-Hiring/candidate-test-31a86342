import calendar
import datetime
from collections import defaultdict
from functools import partial
from smtplib import SMTPException

from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Prefetch, QuerySet, Sum
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Company, CompanyAdmin, Freelancer
from accounts.permissions import IsCompanyAdmin
from contracts.models import TimesheetEntry

from .enums import BillingRunStatus, InvoiceEmailRecipient, InvoiceEmailStatus
from .models import BillingRun, Invoice, InvoiceEmail, InvoiceLine
from .serializers import InvoiceDetailSerializer, InvoiceSerializer


def _company_admin(request: Request) -> CompanyAdmin:
    # IsCompanyAdmin has already checked this; narrows the type and reuses its cached lookup.
    user = request.user
    if not isinstance(user, User):
        raise PermissionDenied
    return user.company_admin


# Possibly a contender for some more 'core' util, but here for now:
def _parse_month(raw: object) -> tuple[datetime.date, datetime.date]:
    if isinstance(raw, str):
        try:
            start = datetime.datetime.strptime(raw, '%Y-%m').date()
        except ValueError:
            pass
        else:
            _, last_day = calendar.monthrange(start.year, start.month)
            return start, start.replace(day=last_day)
    raise ValidationError({'month': 'Expected a month in YYYY-MM format.'})


# Email sending lives here for now, alongside the run; see CANDIDATE_NOTES.md.
def _current_address(email: InvoiceEmail, invoice: Invoice) -> str:
    match InvoiceEmailRecipient(email.recipient):
        case InvoiceEmailRecipient.COMPANY:
            return invoice.company.billing_email
        case InvoiceEmailRecipient.FREELANCER:
            return invoice.freelancer.user.email


def _attempt_send(email: InvoiceEmail) -> None:
    invoice = (
        _invoices_with_totals()
        .select_related('company', 'freelancer__user')
        .get(pk=email.invoice_id)
    )
    body = render_to_string(
        'billing/invoice_email.txt',
        {'invoice': invoice, 'lines': invoice.invoiceline_set.order_by('date', 'id')},
    )
    subject = (
        f'Invoice {invoice.pk}: {invoice.freelancer.name} for {invoice.company.name}, '
        f'{invoice.period_start} to {invoice.period_end}'
    )
    email.to_address = _current_address(email, invoice)
    try:
        send_mail(subject, body, None, [email.to_address])
    except (SMTPException, OSError) as exc:
        email.status = InvoiceEmailStatus.FAILED
        email.last_error = str(exc)
    else:
        email.status = InvoiceEmailStatus.SENT
        email.last_error = ''
        email.sent_at = timezone.now()
    email.save(update_fields=['to_address', 'status', 'last_error', 'sent_at'])


def _send_invoice_emails(email_ids: list[int]) -> None:
    for email_id in email_ids:
        # One transaction per email, so a slow or failing send doesn't hold the others.
        with transaction.atomic():
            email = (
                InvoiceEmail.objects.select_for_update(skip_locked=True)
                .exclude(status=InvoiceEmailStatus.SENT)
                .filter(pk=email_id)
                .first()
            )
            if email is not None:
                _attempt_send(email)


class BillingRunView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyAdmin]

    def post(self, request: Request) -> Response:
        admin = _company_admin(request)
        period_start, period_end = _parse_month(request.data.get('month'))
        today = timezone.localdate()
        if period_start > today:
            raise ValidationError({'month': 'Months that have not started cannot be billed.'})
        billable_until = min(period_end, today)

        with transaction.atomic():
            # Serialises concurrent runs for the same company.
            company = Company.objects.select_for_update().get(pk=admin.company_id)
            run = BillingRun.objects.create(
                company=company,
                period_start=period_start,
                period_end=period_end,
                triggered_by=admin.user,
            )

            unbilled_entries = (
                TimesheetEntry.objects.filter(
                    contract__company=company,
                    status=TimesheetEntry.STATUS_APPROVED,
                    date__range=(period_start, billable_until),
                    invoiceline__isnull=True,
                )
                .select_related('contract__freelancer__user')
                .order_by('date')
            )
            entries_by_freelancer: defaultdict[Freelancer, list[TimesheetEntry]] = defaultdict(list)
            for entry in unbilled_entries:
                entries_by_freelancer[entry.contract.freelancer].append(entry)

            invoices = Invoice.objects.bulk_create(
                Invoice(
                    billing_run=run,
                    company=company,
                    freelancer=freelancer,
                    period_start=period_start,
                    period_end=period_end,
                )
                for freelancer in entries_by_freelancer
            )
            InvoiceLine.objects.bulk_create(
                InvoiceLine(
                    invoice=invoice,
                    timesheet_entry=entry,
                    date=entry.date,
                    hours=entry.hours,
                    daily_rate=entry.contract.daily_rate,
                )
                for invoice in invoices
                for entry in entries_by_freelancer[invoice.freelancer]
            )
            InvoiceEmail.objects.bulk_create(
                email
                for invoice in invoices
                for email in (
                    InvoiceEmail(
                        invoice=invoice,
                        recipient=InvoiceEmailRecipient.COMPANY,
                        to_address=company.billing_email,
                    ),
                    InvoiceEmail(
                        invoice=invoice,
                        recipient=InvoiceEmailRecipient.FREELANCER,
                        to_address=invoice.freelancer.user.email,
                    ),
                )
            )

            run.status = BillingRunStatus.COMPLETED
            run.save(update_fields=['status'])

            # Includes emails that failed on earlier runs for this month, so a re-run retries them.
            unsent_email_ids = list(
                InvoiceEmail.objects.filter(
                    invoice__company=company,
                    invoice__period_start__lte=period_end,
                    invoice__period_end__gte=period_start,
                )
                .exclude(status=InvoiceEmailStatus.SENT)
                .values_list('id', flat=True)
            )
            transaction.on_commit(partial(_send_invoice_emails, unsent_email_ids))

        return Response(
            {
                'run_id': run.pk,
                'invoices_generated': len(invoices),
                'status': run.status,
            },
            status=status.HTTP_201_CREATED,
        )


def _invoices_with_totals() -> QuerySet[Invoice]:
    return Invoice.objects.annotate(total=Sum('invoiceline__daily_rate'))


def _company_invoices(company_id: int) -> QuerySet[Invoice]:
    return _invoices_with_totals().filter(company_id=company_id).select_related('freelancer')


class InvoiceListView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyAdmin]

    def get(self, request: Request) -> Response:
        admin = _company_admin(request)
        period_start, period_end = _parse_month(request.query_params.get('month'))
        invoices = (
            _company_invoices(admin.company_id)
            .filter(period_start__lte=period_end, period_end__gte=period_start)
            .order_by('freelancer__name', 'id')
        )
        return Response(InvoiceSerializer(invoices, many=True).data)


class InvoiceDetailView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyAdmin]

    def get(self, request: Request, pk: int) -> Response:
        admin = _company_admin(request)
        try:
            invoice = (
                _company_invoices(admin.company_id)
                .select_related('company')
                .prefetch_related(
                    Prefetch('invoiceline_set', queryset=InvoiceLine.objects.order_by('date', 'id'))
                )
                .get(pk=pk)
            )
        except Invoice.DoesNotExist:
            raise NotFound from None
        return Response(InvoiceDetailSerializer(invoice).data)
