import { createDocumentResource } from 'frappe-ui'
import { reactive, ref } from 'vue'

const settings = ref({})
const brand = reactive({})

const _settings = createDocumentResource({
  doctype: 'FCRM Settings',
  name: 'FCRM Settings',
  onSuccess: (data) => {
    settings.value = data
    getSettings().setupBrand()
    return data
  },
})

export function getSettings() {
  function setupBrand() {
    const configuredName = settings.value?.brand_name?.trim()
    brand.name =
      !configuredName || /frappe|twenty|^20$/i.test(configuredName)
        ? 'Baton'
        : configuredName
    brand.logo = settings.value?.brand_logo
    brand.favicon =
      settings.value?.favicon || '/assets/crm/images/pulp-orange-192.png'
  }

  return {
    _settings,
    settings,
    brand,
    setupBrand,
  }
}
