from rest_framework import serializers

from accounts.serializers import CompanySerializer, FreelancerSerializer

from .models import Invoice, InvoiceLine


class InvoiceSerializer(serializers.ModelSerializer[Invoice]):
    freelancer = FreelancerSerializer(read_only=True)
    total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id',
            'billing_run',
            'freelancer',
            'period_start',
            'period_end',
            'total',
            'created_at',
        ]


class InvoiceLineSerializer(serializers.ModelSerializer[InvoiceLine]):
    class Meta:
        model = InvoiceLine
        fields = ['id', 'timesheet_entry', 'date', 'hours', 'daily_rate']


class InvoiceDetailSerializer(InvoiceSerializer):
    company = CompanySerializer(read_only=True)
    lines = InvoiceLineSerializer(source='invoiceline_set', many=True, read_only=True)

    class Meta(InvoiceSerializer.Meta):
        fields = [
            'id',
            'billing_run',
            'company',
            'freelancer',
            'period_start',
            'period_end',
            'total',
            'created_at',
            'lines',
        ]
