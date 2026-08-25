export function buildExportUrl(spec) {
  const params = new URLSearchParams({
    file_format_type: spec.file_format === 'Excel' ? 'Excel' : 'CSV',
    title: spec.doctype,
    doctype: spec.doctype,
    fields: JSON.stringify(spec.fields || ['name']),
    filters: JSON.stringify(spec.filters || {}),
    order_by: spec.order_by || 'modified desc',
    page_length: String(spec.limit || 5000),
    start: '0',
    view: 'Report',
    with_comment_count: '1',
  })

  return `/api/method/frappe.desk.reportview.export_query?${params.toString()}`
}

export function downloadExport(spec) {
  const link = document.createElement('a')
  link.href = buildExportUrl(spec)
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
}
