import datetime

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from billing.tests.factories import make_invoice
from contracts.models import Contract

APRIL_START = datetime.date(2026, 4, 1)
APRIL_END = datetime.date(2026, 4, 30)


@pytest.mark.django_db
def test_detail_returns_invoice_with_company_lines_in_date_order_and_total(
    admin_client: APIClient, admin_user: User, active_contract: Contract
) -> None:
    invoice = make_invoice(
        active_contract,
        admin_user,
        APRIL_START,
        APRIL_END,
        [datetime.date(2026, 4, 2), datetime.date(2026, 4, 1)],
    )
    first_line, second_line = invoice.invoiceline_set.order_by('date')
    company = active_contract.company

    resp = admin_client.get(f'/api/invoices/{invoice.pk}/')

    assert resp.status_code == 200
    assert resp.json() == {
        'id': invoice.pk,
        'billing_run': invoice.billing_run_id,
        'company': {
            'id': company.pk,
            'name': company.name,
            'billing_email': company.billing_email,
        },
        'freelancer': {'id': active_contract.freelancer.pk, 'name': 'Test Freelancer'},
        'period_start': '2026-04-01',
        'period_end': '2026-04-30',
        'total': '1200.00',
        'created_at': invoice.created_at.isoformat().replace('+00:00', 'Z'),
        'lines': [
            {
                'id': first_line.pk,
                'timesheet_entry': first_line.timesheet_entry_id,
                'date': '2026-04-01',
                'hours': '8.00',
                'daily_rate': '600.00',
            },
            {
                'id': second_line.pk,
                'timesheet_entry': second_line.timesheet_entry_id,
                'date': '2026-04-02',
                'hours': '8.00',
                'daily_rate': '600.00',
            },
        ],
    }


@pytest.mark.django_db
def test_detail_hides_other_companies_invoices(
    admin_client: APIClient, admin_user: User, other_contract: Contract
) -> None:
    invoice = make_invoice(
        other_contract, admin_user, APRIL_START, APRIL_END, [datetime.date(2026, 4, 1)]
    )

    resp = admin_client.get(f'/api/invoices/{invoice.pk}/')

    assert resp.status_code == 404
    assert resp.json() == {'detail': 'Not found.'}


@pytest.mark.django_db
def test_detail_of_missing_invoice_returns_404(admin_client: APIClient) -> None:
    resp = admin_client.get('/api/invoices/999999/')

    assert resp.status_code == 404
    assert resp.json() == {'detail': 'Not found.'}


@pytest.mark.django_db
def test_freelancer_cannot_view_invoice(
    freelancer_client: APIClient, admin_user: User, active_contract: Contract
) -> None:
    invoice = make_invoice(
        active_contract, admin_user, APRIL_START, APRIL_END, [datetime.date(2026, 4, 1)]
    )

    resp = freelancer_client.get(f'/api/invoices/{invoice.pk}/')

    assert resp.status_code == 403


@pytest.mark.django_db
def test_anonymous_user_cannot_view_invoice(api_client: APIClient) -> None:
    resp = api_client.get('/api/invoices/1/')

    assert resp.status_code == 401
