import datetime
from smtplib import SMTPException
from typing import NoReturn

import pytest
from django.core.mail import EmailMessage
from django.core.mail import send_mail as real_send_mail
from pytest_django import DjangoCaptureOnCommitCallbacks
from rest_framework.test import APIClient

from billing.enums import InvoiceEmailRecipient, InvoiceEmailStatus
from billing.models import Invoice, InvoiceEmail
from billing.tests.factories import make_contract, make_entry, make_freelancer
from contracts.models import Contract


def _run_april(client: APIClient, capture: DjangoCaptureOnCommitCallbacks) -> None:
    with capture(execute=True):
        resp = client.post('/api/billing/runs/', {'month': '2026-04'}, format='json')
    assert resp.status_code == 201


def _smtp_down(
    subject: str, message: str, from_email: str | None, recipient_list: list[str]
) -> NoReturn:
    raise SMTPException('connection refused')


def _email(recipient: InvoiceEmailRecipient) -> InvoiceEmail:
    return InvoiceEmail.objects.get(recipient=recipient)


@pytest.mark.django_db
def test_emails_are_only_sent_once_the_run_has_committed(
    admin_client: APIClient,
    active_contract: Contract,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    mailoutbox: list[EmailMessage],
) -> None:
    make_entry(active_contract, datetime.date(2026, 4, 1))

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        admin_client.post('/api/billing/runs/', {'month': '2026-04'}, format='json')

    assert mailoutbox == []
    assert set(InvoiceEmail.objects.values_list('status', flat=True)) == {
        InvoiceEmailStatus.PENDING
    }

    for callback in callbacks:
        callback()

    assert len(mailoutbox) == 2


@pytest.mark.django_db
def test_email_body_is_plain_text_without_html_escaping(
    admin_client: APIClient,
    active_contract: Contract,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    mailoutbox: list[EmailMessage],
) -> None:
    contract = make_contract(active_contract.company, make_freelancer("O'Brien & <Sons>"))
    make_entry(contract, datetime.date(2026, 4, 1))

    _run_april(admin_client, django_capture_on_commit_callbacks)

    assert all("From: O'Brien & <Sons>" in message.body for message in mailoutbox)


@pytest.mark.django_db
def test_run_emails_invoice_to_company_and_freelancer(
    admin_client: APIClient,
    active_contract: Contract,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    mailoutbox: list[EmailMessage],
) -> None:
    make_entry(active_contract, datetime.date(2026, 4, 1))
    make_entry(active_contract, datetime.date(2026, 4, 2))

    _run_april(admin_client, django_capture_on_commit_callbacks)

    invoice = Invoice.objects.get()
    assert sorted(address for message in mailoutbox for address in message.to) == sorted(
        [active_contract.company.billing_email, active_contract.freelancer.user.email]
    )
    for message in mailoutbox:
        assert message.subject == (
            f'Invoice {invoice.pk}: Test Freelancer for NorthStar Consulting, '
            '2026-04-01 to 2026-04-30'
        )
        assert '2026-04-01' in message.body
        assert '2026-04-02' in message.body
        assert 'Total: 1200.00' in message.body
    for email in InvoiceEmail.objects.all():
        assert email.status == InvoiceEmailStatus.SENT
        assert email.sent_at is not None
        assert email.last_error == ''


@pytest.mark.django_db
def test_failed_send_keeps_the_invoice_and_marks_the_email_failed(
    admin_client: APIClient,
    active_contract: Contract,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_entry(active_contract, datetime.date(2026, 4, 1))
    monkeypatch.setattr('billing.views.send_mail', _smtp_down)

    _run_april(admin_client, django_capture_on_commit_callbacks)

    assert Invoice.objects.count() == 1
    for email in InvoiceEmail.objects.all():
        assert email.status == InvoiceEmailStatus.FAILED
        assert email.last_error == 'connection refused'
        assert email.sent_at is None


@pytest.mark.django_db
def test_one_recipient_failing_does_not_stop_the_other(
    admin_client: APIClient,
    active_contract: Contract,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    mailoutbox: list[EmailMessage],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    billing_email = active_contract.company.billing_email

    def _reject_billing_address(
        subject: str, message: str, from_email: str | None, recipient_list: list[str]
    ) -> int:
        if recipient_list == [billing_email]:
            raise SMTPException('mailbox unavailable')
        return real_send_mail(subject, message, from_email, recipient_list)

    make_entry(active_contract, datetime.date(2026, 4, 1))
    monkeypatch.setattr('billing.views.send_mail', _reject_billing_address)

    _run_april(admin_client, django_capture_on_commit_callbacks)

    assert _email(InvoiceEmailRecipient.COMPANY).status == InvoiceEmailStatus.FAILED
    assert _email(InvoiceEmailRecipient.FREELANCER).status == InvoiceEmailStatus.SENT
    assert [message.to for message in mailoutbox] == [[active_contract.freelancer.user.email]]


@pytest.mark.django_db
def test_rerun_retries_failed_email_at_the_current_address(
    admin_client: APIClient,
    active_contract: Contract,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    mailoutbox: list[EmailMessage],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_entry(active_contract, datetime.date(2026, 4, 1))
    with monkeypatch.context() as smtp:
        smtp.setattr('billing.views.send_mail', _smtp_down)
        _run_april(admin_client, django_capture_on_commit_callbacks)
    company = active_contract.company
    company.billing_email = 'corrected@northstar.test'
    company.save()

    _run_april(admin_client, django_capture_on_commit_callbacks)

    retried = _email(InvoiceEmailRecipient.COMPANY)
    assert retried.status == InvoiceEmailStatus.SENT
    assert retried.to_address == 'corrected@northstar.test'
    assert 'corrected@northstar.test' in [
        address for message in mailoutbox for address in message.to
    ]
    assert _email(InvoiceEmailRecipient.FREELANCER).status == InvoiceEmailStatus.SENT


@pytest.mark.django_db
def test_sent_email_is_not_resent_or_readdressed(
    admin_client: APIClient,
    active_contract: Contract,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    mailoutbox: list[EmailMessage],
) -> None:
    make_entry(active_contract, datetime.date(2026, 4, 1))
    _run_april(admin_client, django_capture_on_commit_callbacks)
    original_address = active_contract.company.billing_email
    company = active_contract.company
    company.billing_email = 'changed@northstar.test'
    company.save()

    _run_april(admin_client, django_capture_on_commit_callbacks)

    assert len(mailoutbox) == 2
    assert _email(InvoiceEmailRecipient.COMPANY).to_address == original_address
