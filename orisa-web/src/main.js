import Vue from 'vue'
import App from './App.vue'
import router from './router'

import BootstrapVue from 'bootstrap-vue'
import axios from 'axios'

import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap-vue/dist/bootstrap-vue.css'

Vue.config.productionTip = false

Vue.use(BootstrapVue)

Vue.prototype.$http = axios
axios.defaults.baseURL = process.env.VUE_APP_BOT_BASE_URL

new Vue({
  router,
  render: h => h(App)
}).$mount('#app')
