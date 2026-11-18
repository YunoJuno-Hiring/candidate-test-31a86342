import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { fetchInvoice } from '../api/billing'
import { ApiError } from '../api/client'

export default function InvoiceDetail() {
  const { id } = useParams<{ id: string }>()

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['invoice', id],
    queryFn: () => fetchInvoice(id!),
    retry: false,
  })

  const isNotFound = isError && error instanceof ApiError && error.status === 404

  if (isLoading) {
    return <p className="text-slate-500">Loading invoice…</p>
  }

  if (isNotFound) {
    return (
      <div>
        <Link to="/billing" className="text-indigo-600 hover:text-indigo-800 text-sm mb-4 inline-block">
          ← Billing
        </Link>
        <div className="bg-white border border-slate-200 rounded-lg px-6 py-12 text-center max-w-md">
          <p className="text-slate-800 font-medium">Invoice not found</p>
          <p className="text-slate-500 text-sm mt-1">
            This invoice doesn't exist yet — billing may not have run for this period.
          </p>
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 rounded px-4 py-3 text-sm">
        Failed to load invoice.
      </div>
    )
  }

  if (data === undefined) {
    return null
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to="/billing" className="text-indigo-600 hover:text-indigo-800 text-sm mb-2 inline-block">
          ← Billing
        </Link>
        <h1 className="text-xl font-semibold text-slate-900">Invoice #{data.id}</h1>
        <p className="text-slate-500 text-sm mt-1">
          {data.period_start} – {data.period_end}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 max-w-2xl">
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">From</p>
          <p className="text-slate-800 font-medium">{data.freelancer.name}</p>
        </div>
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">Billed to</p>
          <p className="text-slate-800 font-medium">{data.company.name}</p>
          <p className="text-slate-500 text-sm">{data.company.billing_email}</p>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-slate-600">Date</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">Hours</th>
              <th className="text-right px-4 py-3 font-medium text-slate-600">Day rate</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.lines.map((line) => (
              <tr key={line.id}>
                <td className="px-4 py-3 text-slate-700">{line.date}</td>
                <td className="px-4 py-3 text-slate-700">{line.hours}h</td>
                <td className="px-4 py-3 text-right text-slate-700">
                  £{Number(line.daily_rate).toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot className="bg-slate-50 border-t border-slate-200">
            <tr>
              <td colSpan={2} className="px-4 py-3 font-medium text-slate-700">
                Total ({data.lines.length} {data.lines.length === 1 ? 'day' : 'days'})
              </td>
              <td className="px-4 py-3 text-right font-semibold text-slate-900">
                £{Number(data.total).toFixed(2)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}
