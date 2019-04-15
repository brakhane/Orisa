import Vue from 'vue'
import Buefy from 'buefy'
import App from './App'

import router from './router'

import 'buefy/dist/buefy.css'

Vue.use(Buefy, {
  // defaultIconPack: 'fas'
})

new Vue({
  router,
  render: h => h(App)
}).$mount('#app')
