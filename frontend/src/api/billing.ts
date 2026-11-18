import { api, BillingRunResult, Invoice, InvoiceWithLines } from './client'

export function runBilling(month: string): Promise<BillingRunResult> {
  return api.post('/api/billing/runs/', { month })
}

export function fetchInvoices(month: string): Promise<Invoice[]> {
  return api.get(`/api/invoices/?month=${month}`)
}

export function fetchInvoice(id: string): Promise<InvoiceWithLines> {
  return api.get(`/api/invoices/${id}/`)
}
