import { describe, expect, it } from 'vitest'
import { buildExportUrl } from '../../src/utils/chatActions'

describe('Ask Pulp exports', () => {
  it('uses the existing permission-aware report export endpoint', () => {
    const url = buildExportUrl({
      doctype: 'CRM Lead',
      fields: ['name', 'lead_name'],
      filters: { status: 'Open & Active' },
      order_by: 'modified desc',
      limit: 250,
      file_format: 'CSV',
    })
    const parsed = new URL(url, 'https://pulp.test')

    expect(parsed.pathname).toBe(
      '/api/method/frappe.desk.reportview.export_query',
    )
    expect(JSON.parse(parsed.searchParams.get('filters'))).toEqual({
      status: 'Open & Active',
    })
    expect(parsed.searchParams.get('page_length')).toBe('250')
    expect(parsed.searchParams.get('file_format_type')).toBe('CSV')
  })
})
