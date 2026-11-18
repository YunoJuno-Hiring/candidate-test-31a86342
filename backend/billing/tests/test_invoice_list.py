import datetime

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from billing.tests.factories import make_contract, make_freelancer, make_invoice
from contracts.models import Contract

APRIL_START = datetime.date(2026, 4, 1)
APRIL_END = datetime.date(2026, 4, 30)


def _listed_ids(client: APIClient, month: str) -> list[int]:
    resp = client.get(f'/api/invoices/?month={month}')
    assert resp.status_code == 200
    return [invoice['id'] for invoice in resp.json()]


@pytest.mark.django_db
def test_list_returns_invoice_with_total_of_its_lines(
    admin_client: APIClient, admin_user: User, active_contract: Contract
) -> None:
    invoice = make_invoice(
        active_contract,
        admin_user,
        APRIL_START,
        APRIL_END,
        [datetime.date(2026, 4, 1), datetime.date(2026, 4, 2)],
    )

    resp = admin_client.get('/api/invoices/?month=2026-04')

    assert resp.status_code == 200
    assert resp.json() == [
        {
            'id': invoice.pk,
            'billing_run': invoice.billing_run_id,
            'freelancer': {'id': active_contract.freelancer.pk, 'name': 'Test Freelancer'},
            'period_start': '2026-04-01',
            'period_end': '2026-04-30',
            'total': '1200.00',
            'created_at': invoice.created_at.isoformat().replace('+00:00', 'Z'),
        }
    ]


@pytest.mark.django_db
def test_list_includes_invoices_whose_period_overlaps_the_month(
    admin_client: APIClient, admin_user: User, active_contract: Contract
) -> None:
    spanning_month_end = make_invoice(
        active_contract,
        admin_user,
        datetime.date(2026, 4, 27),
        datetime.date(2026, 5, 3),
        [datetime.date(2026, 4, 27)],
    )
    march = make_invoice(
        active_contract,
        admin_user,
        datetime.date(2026, 3, 1),
        datetime.date(2026, 3, 31),
        [datetime.date(2026, 3, 2)],
    )

    assert _listed_ids(admin_client, '2026-04') == [spanning_month_end.pk]
    assert _listed_ids(admin_client, '2026-05') == [spanning_month_end.pk]
    assert _listed_ids(admin_client, '2026-03') == [march.pk]


@pytest.mark.django_db
def test_list_excludes_other_companies_invoices(
    admin_client: APIClient, admin_user: User, other_contract: Contract
) -> None:
    make_invoice(other_contract, admin_user, APRIL_START, APRIL_END, [datetime.date(2026, 4, 1)])

    assert _listed_ids(admin_client, '2026-04') == []


@pytest.mark.django_db
def test_list_orders_by_freelancer_name_then_creation(
    admin_client: APIClient,
    admin_user: User,
    active_contract: Contract,
) -> None:
    second_contract = make_contract(active_contract.company, make_freelancer('Second Freelancer'))
    original = make_invoice(
        active_contract, admin_user, APRIL_START, APRIL_END, [datetime.date(2026, 4, 1)]
    )
    second_freelancers = make_invoice(
        second_contract, admin_user, APRIL_START, APRIL_END, [datetime.date(2026, 4, 1)]
    )
    supplementary = make_invoice(
        active_contract, admin_user, APRIL_START, APRIL_END, [datetime.date(2026, 4, 2)]
    )

    assert _listed_ids(admin_client, '2026-04') == [
        second_freelancers.pk,
        original.pk,
        supplementary.pk,
    ]


@pytest.mark.django_db
@pytest.mark.parametrize('query', ['', '?month=', '?month=April', '?month=2026-13'])
def test_list_rejects_malformed_or_missing_month(admin_client: APIClient, query: str) -> None:
    resp = admin_client.get(f'/api/invoices/{query}')

    assert resp.status_code == 400


@pytest.mark.django_db
def test_freelancer_cannot_list_invoices(freelancer_client: APIClient) -> None:
    resp = freelancer_client.get('/api/invoices/?month=2026-04')

    assert resp.status_code == 403


@pytest.mark.django_db
def test_anonymous_user_cannot_list_invoices(api_client: APIClient) -> None:
    resp = api_client.get('/api/invoices/?month=2026-04')

    assert resp.status_code == 401
