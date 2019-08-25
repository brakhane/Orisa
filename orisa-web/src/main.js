/*
Orisa, a simple Discord bot with good intentions
Copyright (C) 2018, 2019 Dennis Brakhane

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, version 3 only

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import Vue from 'vue'
import App from './App.vue'
import router from './router'

import BootstrapVue from 'bootstrap-vue'
import VueI18Next from '@panter/vue-i18next'
import VueMarkdown from 'vue-markdown'
import i18next from 'i18next'
import axios from 'axios'

import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap-vue/dist/bootstrap-vue.css'

import de from '@/locale/de.json'
import en from '@/locale/en.json'

Vue.config.productionTip = false

Vue.use(VueI18Next)
Vue.use(BootstrapVue)

Vue.component('vue-markdown', VueMarkdown)

const data = {
  lng: 'de',
  fallbackLng: 'en',
  debug: true,
  resources: {
    de: { translation: de },
    en: { translation: en }
  }
}

i18next.init(data)
console.log(data)

const i18n = new VueI18Next(i18next)

Vue.prototype.$http = axios
axios.defaults.baseURL = process.env.VUE_APP_BOT_BASE_URL

new Vue({
  router,
  i18n,
  render: h => h(App)
}).$mount('#app')
